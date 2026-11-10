import { NextResponse } from "next/server";
import { paymentState, payOrder, PaymentPageError } from "@/lib/lumi-payment-page";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
type Context = {params: Promise<{token: string; action: string}>};
async function handle(request: Request, context: Context) {
  const {token, action} = await context.params;
  try {
    let result;
    if (request.method === "GET" && action === "state") result = await paymentState(token);
    else if (request.method === "POST" && action === "pay") {
      const text = await request.text();
      if (text.length > 8192) return NextResponse.json({error: "Dados inválidos."}, {status: 413});
      let body; try {body = JSON.parse(text);} catch {throw new PaymentPageError("Dados inválidos.");}
      if (!body || Array.isArray(body) || typeof body !== "object") throw new PaymentPageError("Dados inválidos.");
      result = await payOrder(token, body, request.headers.get("origin"), new URL(request.url).origin);
    } else return NextResponse.json({error: "Operação indisponível."}, {status: 404});
    return NextResponse.json(result, {headers: {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}});
  } catch (error) {
    if (!(error instanceof PaymentPageError)) console.warn("lumi-payment-page-failed");
    return NextResponse.json({error: error instanceof PaymentPageError ? error.message : "Não foi possível consultar o pagamento."},
      {status: error instanceof PaymentPageError ? error.status : 503, headers: {"Cache-Control": "no-store"}});
  }
}
export const GET = handle;
export const POST = handle;
