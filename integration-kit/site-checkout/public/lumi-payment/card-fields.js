const I={
 ok:'<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="8"/><path d="M6.5 10.2l2.4 2.4 4.6-4.9"/></svg>',
 alert:'<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2.5l8 14.5H2z"/><path d="M10 8v4M10 14.5v.1"/></svg>',
 lock:'<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="9" width="12" height="8" rx="2"/><path d="M7 9V6.5a3 3 0 016 0V9"/></svg>',
 copy:'<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M13 7V5a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2"/></svg>',
 clock:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
 big:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path class="draw" d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
 wa:'<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h12a1 1 0 011 1v8a1 1 0 01-1 1H9l-4 3v-3H4a1 1 0 01-1-1V5a1 1 0 011-1z"/></svg>',
 tick:'<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3.2L13 4.8"/></svg>'
};


const digits=s=>s.replace(/\D/g,"");
function luhn(n){let s=0,alt=false;for(let i=n.length-1;i>=0;i--){let d=+n[i];if(alt){d*=2;if(d>9)d-=9}s+=d;alt=!alt}return s%10===0}
function brandOf(n){
  if(/^3[47]/.test(n))return"amex";
  if(/^(4011|4312|4389|4514|4576|5041|5066|5067|509|6277|6362|6363|650|6516|6550)/.test(n))return"elo";
  if(/^(606282|3841)/.test(n))return"hiper";
  if(/^4/.test(n))return"visa";
  if(/^(5[1-5]|222[1-9]|22[3-9]\d|2[3-6]\d\d|27[01]\d|2720)/.test(n))return"master";
  return"";
}
const BN={visa:"Visa",master:"Mastercard",amex:"Amex",elo:"Elo",hiper:"Hipercard"};
function fmtNum(n,b){n=n.slice(0,b==="amex"?15:16);const g=b==="amex"?[4,6,5]:[4,4,4,4];let o=[],i=0;for(const k of g){if(i>=n.length)break;o.push(n.slice(i,i+k));i+=k}return o.join(" ")}
const V={
 number(v){const n=digits(v),b=brandOf(n);
  if(!n)return"Informe o número do cartão.";
  if(n.length<(b==="amex"?15:16))return"Número incompleto. Confira os dígitos.";
  if(!luhn(n))return"Número de cartão inválido. Confira e tente de novo.";
  if(!b)return"Bandeira não aceita. Use Visa, Mastercard, Elo, Amex ou Hipercard.";return""},
 name(v){const t=v.trim();
  if(!t)return"Informe o nome como está no cartão.";
  if(t.split(/\s+/).length<2||!/^[A-Za-zÀ-ÿ'\s.-]+$/.test(t))return"Digite nome e sobrenome, como está no cartão.";return""},
 exp(v){const d=digits(v);
  if(d.length<4)return"Use o formato MM/AA.";
  const m=+d.slice(0,2),y=2000+ +d.slice(2,4),now=new Date();
  if(m<1||m>12)return"Mês inválido.";
  if(y<now.getFullYear()||(y===now.getFullYear()&&m<now.getMonth()+1))return"Cartão vencido. Use outro cartão.";
  if(y>now.getFullYear()+20)return"Validade inválida.";return""},
 cvv(v,b){const d=digits(v),len=b==="amex"?4:3;
  if(d.length<len)return b==="amex"?"Informe os 4 dígitos da frente do cartão.":"Informe os 3 dígitos do verso do cartão.";return""}
};


export {I,digits,brandOf,BN,fmtNum,V};
