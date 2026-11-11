/** Adapter for the isolated site HML. Uses the site's existing Cielo and ticket pipeline. */
import { createHmac, timingSafeEqual } from "node:crypto";
import { getIngressoDbPool } from "@/lib/ingresso-db";
import { lumiEnabled } from "@/lib/lumi-access";
import { isLocalPaymentDemo } from "@/lib/lumi-demo-payment";
import { createNativeCieloCheckout, getNativeCieloCheckoutStatus } from "@/lib/cielo-ecommerce";
import { reconcilePaymentFromGatewayPayload } from "@/lib/payment-reconciliation";

type Order = {
  token: string; purchase_id: number; cpf: string; expires_at: Date; stcompra: string;
  buyer: {name: string; phone: string; email?: string};
  selection: {date: string; summary: {totalValue: string; lines: {title: string; quantity: number; unitPrice: string}[]}};
};
type Payment = { state: string; method?: string; payment_id?: string; qr_code?: string; qr_image?: string };
export class PaymentPageError extends Error {
  constructor(message: string, public status = 400) { super(message); }
}
function guard() {
  if (!lumiEnabled() || !isLocalPaymentDemo() || (process.env.LUMI_COMMERCE_SECRET || "").length < 32)
    throw new PaymentPageError("Checkout de demonstração indisponível.", 503);
}
async function orderFor(token: string): Promise<Order> {
  guard();
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) throw new PaymentPageError("Link inválido ou expirado.", 404);
  const result = await getIngressoDbPool().query<Order>(`SELECT o.*, c.stcompra FROM lumi_orders o
    JOIN compra c ON c.idcompra=o.purchase_id WHERE o.token=$1 AND o.tenant_id=$2
    AND o.expires_at>now() AND c.stcompra<>'canc'`, [token, process.env.LUMI_TENANT_ID]);
  if (!result.rows[0]) throw new PaymentPageError("Link inválido ou expirado.", 404);
  return result.rows[0];
}
function csrf(token: string) {
  return createHmac("sha256", process.env.LUMI_COMMERCE_SECRET!).update("payment:" + token).digest("hex");
}
function normalizePayment(raw: Awaited<ReturnType<typeof getNativeCieloCheckoutStatus>>): Payment {
  const sale = raw.sale as { Payment?: {PaymentId?: string; Type?: string; Status?: number; QrCodeString?: string; QrCodeBase64Image?: string} } | null;
  const payment = sale?.Payment;
  if (!payment?.PaymentId) return {state: "unknown"};
  return {state: payment.Status === 2 ? "issuing_tickets" : [3,10,11,13].includes(payment.Status ?? -1) ? "denied" : "pending",
    method: payment.Type, payment_id: payment.PaymentId, qr_code: payment.QrCodeString, qr_image: payment.QrCodeBase64Image};
}
async function storedPayment(token: string): Promise<Payment | null> {
  const result = await getIngressoDbPool().query<{public_data: Payment}>("SELECT public_data FROM lumi_payment_attempts WHERE token=$1", [token]);
  return result.rows[0]?.public_data ?? null;
}
async function savePayment(token: string, data: Payment) {
  await getIngressoDbPool().query("UPDATE lumi_payment_attempts SET public_data=$2::jsonb WHERE token=$1", [token, JSON.stringify(data)]);
}
async function present(order: Order, payment: Payment | null) {
  const status = await getIngressoDbPool().query<{stcompra: string}>("SELECT stcompra FROM compra WHERE idcompra=$1", [order.purchase_id]);
  return { ...payment, state: status.rows[0]?.stcompra === "conc" ? "paid" : status.rows[0]?.stcompra === "canc" ? "expired" : payment?.state ?? "ready",
    order_id: order.purchase_id, buyer_name: order.buyer.name, cpf_masked: "***.***.***-" + order.cpf.slice(-2),
    quote: {visitDate: order.selection.date, totalAmount: Number(order.selection.summary.totalValue),
      items: order.selection.summary.lines.map(line => ({title: line.title, quantity: line.quantity, unit_price: Number(line.unitPrice)}))},
    expires_at: new Date(order.expires_at).getTime()/1000, security_token: csrf(order.token),
    sandbox: true, debit_available: true, debit_demo: true,
    max_installments: Math.min(12, Math.max(1, Number(process.env.INGRESSO_CIELO_MAX_INSTALLMENTS || 1)))};
}
export async function paymentState(token: string) {
  const order = await orderFor(token);
  let payment = await storedPayment(token);
  if (payment && !["paid", "denied"].includes(payment.state) && order.stcompra !== "conc") {
    try {
      const raw = await getNativeCieloCheckoutStatus({paymentId: payment.payment_id, reference: String(order.purchase_id), purchaseId: order.purchase_id});
      // A result found by merchant reference also recovers a timeout after submission.
      if (raw.sale) {
        await reconcilePaymentFromGatewayPayload(raw, order.purchase_id);
        payment = normalizePayment(raw); await savePayment(token, payment);
      }
    } catch { /* Keep the durable uncertain state: never resubmit automatically. */ }
  }
  return present(order, payment);
}
export async function payOrder(token: string, body: Record<string, unknown>, origin: string | null, expectedOrigin: string) {
  const order = await orderFor(token);
  const provided = Buffer.from(String(body.security_token ?? "")), expected = Buffer.from(csrf(token));
  if (origin !== expectedOrigin || provided.length !== expected.length || !timingSafeEqual(provided, expected))
    throw new PaymentPageError("Atualize a página antes de continuar.", 403);
  const methods: Record<string,string> = {pix: "Pix", card: "CreditCard", debit: "DebitCard"};
  const method = Object.hasOwn(methods, String(body.method)) ? methods[String(body.method)] : undefined;
  if (!method) throw new PaymentPageError("Forma de pagamento inválida.");
  if (order.stcompra === "conc") return present(order, await storedPayment(token));
  if (method !== "Pix" && (!/^\d{13,19}$/.test(String(body.card_number ?? "")) || !/^\d{3,4}$/.test(String(body.security_code ?? "")) ||
      !/^\d{2}\/\d{4}$/.test(String(body.expiration ?? "")) || String(body.holder ?? "").trim().length < 2 ||
      !["Visa","Master","Elo","Amex","Hipercard"].includes(String(body.brand))))
    throw new PaymentPageError("Confira os dados do cartão.");
  // Reserve before calling the gateway. Concurrent requests and a lost response cannot create another charge.
  const reserved = await getIngressoDbPool().query(`INSERT INTO lumi_payment_attempts(token,public_data)
    VALUES($1,$2::jsonb) ON CONFLICT(token) DO NOTHING RETURNING token`, [token, JSON.stringify({state: "unknown", method})]);
  if (!reserved.rows.length) return paymentState(token);
  try {
    // An order previously opened through the old site widget must not be charged again.
    const previous = await getIngressoDbPool().query("SELECT idpagseguro FROM pagpagseguro WHERE idcompra=$1 LIMIT 1", [order.purchase_id]);
    if (previous.rows.length) return paymentState(token);
    const raw = await createNativeCieloCheckout({purchaseId: order.purchase_id, amount: order.selection.summary.totalValue,
      customer: {name: order.buyer.name, document: order.cpf, phone: order.buyer.phone, email: order.buyer.email || ""},
      payment: {type: method, cardNumber: body.card_number, holder: body.holder, expirationDate: body.expiration,
        securityCode: body.security_code, brand: body.brand, installments: method === "DebitCard" ? 1 : body.installments},
      returnUrl: expectedOrigin + "/pagar/" + token});
    await reconcilePaymentFromGatewayPayload(raw, order.purchase_id);
    const payment = normalizePayment(raw); await savePayment(token, payment);
    return present(order, payment);
  } catch {
    console.warn("lumi-payment-awaiting-reconciliation", {purchaseId: order.purchase_id});
    return present(order, {state: "unknown", method});
  }
}
