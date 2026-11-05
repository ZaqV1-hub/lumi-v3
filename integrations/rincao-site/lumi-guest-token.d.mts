export interface GuestClaim { purpose: 'guest-account'; cpf: string; phone: string; order_id: string; exp: number; }
export function decodeGuestClaim(token: unknown, cpf: string, keyBase64?: string, now?: number): GuestClaim | null;
