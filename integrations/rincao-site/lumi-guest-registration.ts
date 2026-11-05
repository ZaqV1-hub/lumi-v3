import {getIngressoSistemaDbPool} from '@/lib/ingresso-db';
import {hashPasswordForLegacyUser} from '@/lib/password-hashing';
import {createPublicUser as createRegularUser, getActivePublicUserByCpf} from '@/lib/user-repository';
import {decodeGuestClaim} from '@/lib/lumi-guest-token.mjs';

type Registration = Parameters<typeof createRegularUser>[0];
function claims(token: unknown, cpf: string) {
  return decodeGuestClaim(token, cpf, process.env.RINCAO_GUEST_CLAIM_KEY);
}
const permitted = `cpf = $1 AND idpapel IS NULL AND stusuario = 'ati' AND NULLIF(TRIM(senha), '') IS NULL
  AND NULLIF(TRIM(email), '') IS NULL
  AND right(regexp_replace(coalesce(nullif(celular,''),telefone,''),'[^0-9]','','g'),11) = right($17,11)
  AND EXISTS (SELECT 1 FROM compra c WHERE c.cpf=usuario.cpf AND c.idcompra=$18
              AND c.stcompra='conc' AND c.origem_checkout='lumi')`;

export async function canClaimGuest(cpf: string, token: unknown) {
  const proof = claims(token, cpf);
  if (!proof) return false;
  const result = await getIngressoSistemaDbPool().query(`SELECT cpf FROM usuario WHERE ${permitted.replaceAll('$17','$2').replaceAll('$18','$3')}`,
    [cpf, proof.phone, proof.order_id]);
  return result.rows.length === 1;
}

export async function createPublicUserWithGuestClaim(input: Registration, token?: unknown) {
  if (!token) return createRegularUser(input);
  const proof = claims(token, input.cpf);
  if (!proof) throw Error('guest_claim_invalid');
  const result = await getIngressoSistemaDbPool().query(`UPDATE usuario SET
    senha=$2,nmusuario=$3,rg=$4,dtnascimento=$5,sexo=$6,email=$7,telefone=$8,celular=$9,
    endereco=$10,numero=$11,cep=$12,bairro=$13,uf=$14,cidade=$15,complemento=$16
    WHERE ${permitted} RETURNING cpf`, [input.cpf, hashPasswordForLegacyUser(input.password),
      input.name,input.rg,input.birthDate,input.sex,input.email,input.phone,input.mobile,
      input.address,input.number,input.cep,input.district,input.uf,input.cityId,input.complement,
      proof.phone,proof.order_id]);
  if (result.rows.length !== 1) throw Error('guest_account_cannot_be_replaced');
  return getActivePublicUserByCpf(input.cpf);
}
