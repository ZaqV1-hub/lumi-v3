import { readFile } from "node:fs/promises";
import path from "node:path";
import { paymentState, PaymentPageError } from "@/lib/lumi-payment-page";
import { brandName } from "@/lib/site-metadata";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const escape = (value: string) => value.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]!));
export async function GET(_request: Request, {params}: {params: Promise<{token: string}>}) {
  const {token} = await params;
  try {
    await paymentState(token);
    const template = await readFile(path.join(process.cwd(), "public/lumi-payment/index.html"), "utf8");
    const html = template.replaceAll("__TOKEN__", token).replace("<title>Checkout Rincão Ingressos</title>", "<title>Pagamento · Lumi</title>")
      .replaceAll("/checkout/assets/", "/lumi-payment/")
      .replace('data-token="' + token + '"', 'data-token="' + token + '" data-api-base="/api/lumi-payment/' + token + '"')
      .replace('>Rincão<small>', '>' + escape(brandName) + '<small>');
    return new Response(html, {headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
      "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"}});
  } catch (error) {
    return new Response(error instanceof PaymentPageError ? error.message : "Não foi possível abrir o pedido.",
      {status: error instanceof PaymentPageError ? error.status : 503, headers: {"Cache-Control":"no-store"}});
  }
}
