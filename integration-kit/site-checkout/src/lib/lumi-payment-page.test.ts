import { beforeEach, describe, expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({query: vi.fn(), create: vi.fn(), status: vi.fn(), reconcile: vi.fn(), demo: vi.fn()}));
vi.mock("@/lib/ingresso-db", () => ({getIngressoDbPool: () => ({query: mock.query})}));
vi.mock("@/lib/lumi-access", () => ({lumiEnabled: () => true}));
vi.mock("@/lib/lumi-demo-payment", () => ({isLocalPaymentDemo: mock.demo}));
vi.mock("@/lib/cielo-ecommerce", () => ({createNativeCieloCheckout: mock.create, getNativeCieloCheckoutStatus: mock.status}));
vi.mock("@/lib/payment-reconciliation", () => ({reconcilePaymentFromGatewayPayload: mock.reconcile}));
import { paymentState, payOrder } from "./lumi-payment-page";
const token = "x".repeat(43), origin = "http://localhost:3002";
let stored: object | null, submissions: number;
const order = {token, purchase_id: 42, cpf: "00000000000", expires_at: new Date(Date.now()+100000), stcompra:"pend",
  buyer:{name:"Pessoa Teste", phone:"11900000000"}, selection:{date:"2027-01-01",summary:{totalValue:"25.00",lines:[{title:"Ingresso fictício",quantity:1,unitPrice:"25.00"}]}}};
beforeEach(() => {
  vi.clearAllMocks(); vi.stubEnv("LUMI_COMMERCE_SECRET", "s".repeat(40)); vi.stubEnv("LUMI_TENANT_ID", "tenant-test");
  mock.demo.mockReturnValue(true); stored=null; submissions=0;
  mock.query.mockImplementation(async (sql:string, args:unknown[]) => {
    if(sql.includes("JOIN compra")) {expect(args[1]).toBe("tenant-test");return {rows:[order]};}
    if(sql.startsWith("SELECT public_data"))return {rows:stored?[{public_data:stored}]:[]};
    if(sql.startsWith("SELECT stcompra"))return {rows:[{stcompra:"pend"}]};
    if(sql.startsWith("INSERT")){if(submissions++)return {rows:[]};stored=JSON.parse(args[1] as string);return {rows:[{token}]};}
    if(sql.startsWith("UPDATE")){stored=JSON.parse(args[1] as string);return {rows:[]};}
    return {rows:[]};
  });
  mock.create.mockResolvedValue({sale:{Payment:{PaymentId:"fake-payment",Type:"Pix",Status:12,QrCodeString:"FAKE-NOT-PAYABLE"}}});
  mock.status.mockResolvedValue({sale:{Payment:{PaymentId:"fake-payment",Type:"Pix",Status:12}}});
});
describe("Lumi payment page adapter", () => {
  it("shows the same order, masked CPF and three payment methods without a charge", async()=>{
    const state=await paymentState(token);expect(state.order_id).toBe(42);expect(state.quote.totalAmount).toBe(25);
    expect(state.cpf_masked).toBe("***.***.***-00");expect(state.debit_available).toBe(true);expect(state.sandbox).toBe(true);
    expect(mock.create).not.toHaveBeenCalled();
  });
  it("blocks a real gateway, missing order, malformed token and another tenant", async()=>{
    mock.demo.mockReturnValue(false);await expect(paymentState(token)).rejects.toMatchObject({status:503});
    mock.demo.mockReturnValue(true);await expect(paymentState("bad")).rejects.toMatchObject({status:404});
    mock.query.mockResolvedValue({rows:[]});await expect(paymentState(token)).rejects.toMatchObject({status:404});
    expect(mock.create).not.toHaveBeenCalled();
  });
  it("rejects cross-origin and invalid CSRF before submitting", async()=>{
    const state=await paymentState(token);
    await expect(payOrder(token,{method:"pix",security_token:state.security_token},"http://other",origin)).rejects.toMatchObject({status:403});
    await expect(payOrder(token,{method:"pix",security_token:"wrong"},origin,origin)).rejects.toMatchObject({status:403});
    expect(mock.create).not.toHaveBeenCalled();
  });
  it("does not accept inherited object keys as payment methods",async()=>{
    const state=await paymentState(token);
    await expect(payOrder(token,{method:"__proto__",security_token:state.security_token},origin,origin)).rejects.toMatchObject({status:400});
    expect(mock.create).not.toHaveBeenCalled();
  });
  it("reserves atomically, ignores client prices and does not repeat concurrent requests", async()=>{
    const state=await paymentState(token);const body={method:"pix",security_token:state.security_token,amount:1,idcompra:999};
    await Promise.all([payOrder(token,body,origin,origin),payOrder(token,body,origin,origin)]);
    expect(mock.create).toHaveBeenCalledTimes(1);expect(mock.create.mock.calls[0][0]).toMatchObject({purchaseId:42,amount:"25.00"});
    expect(mock.reconcile).toHaveBeenCalled();
  });
  it("keeps a timeout uncertain, recovers by reference and never resubmits",async()=>{
    const state=await paymentState(token);mock.create.mockRejectedValue(new Error("timeout"));
    const body={method:"pix",security_token:state.security_token};
    expect((await payOrder(token,body,origin,origin)).state).toBe("unknown");
    await payOrder(token,body,origin,origin);expect(mock.create).toHaveBeenCalledTimes(1);
    expect(mock.status).toHaveBeenCalledWith({paymentId:undefined,reference:"42",purchaseId:42});
  });
  it("passes credit and debit to the existing site pipeline without persisting card data",async()=>{
    for(const [method,type] of [["card","CreditCard"],["debit","DebitCard"]]) {
      stored=null;submissions=0;
      const state=await paymentState(token);
      await payOrder(token,{method,security_token:state.security_token,card_number:"4111111111111111",security_code:"123",expiration:"12/2030",holder:"Pessoa Teste",brand:"Visa",installments:1},origin,origin);
      expect(mock.create.mock.lastCall?.[0].payment.type).toBe(type);
      expect(JSON.stringify(stored)).not.toContain("4111111111111111");expect(JSON.stringify(stored)).not.toContain("123");
    }
  });
});
