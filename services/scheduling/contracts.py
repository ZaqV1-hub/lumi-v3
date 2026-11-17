from datetime import date
from pydantic import BaseModel, ConfigDict, Field


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Availability(Arguments):
    start_date: date | None
    end_date: date | None
    period: str | None = Field(pattern="^(manha|tarde)$")


class Proposal(Arguments):
    slot_id: str = Field(pattern="^[A-Za-z0-9_-]{32}$")
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=240, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    topic: str = Field(min_length=2, max_length=240)


class Reference(Arguments):
    proposal_id: str = Field(pattern="^[A-Za-z0-9_-]{32}$")

class Participants(Reference):
    emails: list[str] = Field(min_length=0, max_length=10)
    resend_invitations: bool


class Agenda(Arguments):
    start_date: date
    end_date: date

class Description(Reference):
    description: str = Field(min_length=1, max_length=4000)

EDITOR_DEFINITIONS = [
    ("consultar_reunioes_empresa", "/agenda", Agenda,
     "Consultar reuniões confirmadas criadas por esta integração para a própria empresa, em um intervalo de até sete dias. Uso exclusivo dos papéis de gestão de agenda autorizados. Retorna proposal_id e descrição para identificar a reunião correta; não inclui eventos externos ou de outros tenants. O resultado fica na memória desta conversa: após identificar a reunião, use o proposal_id retornado para chamar editar_descricao_reuniao, sem repetir a consulta apenas para recuperar o identificador. A consulta não realiza nenhuma edição."),
    ("editar_descricao_reuniao", "/description", Description,
     "Substituir somente a descrição de uma reunião confirmada da própria empresa, usando proposal_id obtido na consulta e o texto solicitado pelo corretor. Um pedido de edição com reunião e texto identificados deve executar esta ferramenta, não apenas anunciar que fará a alteração. Ao acrescentar uma nota, preserve o conteúdo anterior; se description_truncated=true, solicite uma descrição completa de substituição em vez de reconstruir texto omitido. Esclareça qual reunião quando houver ambiguidade. Não altera data, horário, título, convidados ou Google Meet e não cancela nem reagenda. pending_verification exige consulta posterior, sem repetir a escrita.")]

DEFINITIONS = [
    ("consultar_horarios_reuniao", "/availability", Availability,
     "Consultar horários livres para reunião quando o cliente pedir agendamento ou disponibilidade. Informe um período de até sete dias, com datas locais; campos nulos usam a janela padrão. period pode ser manha, tarde ou null. Os slot_id retornados pertencem a esta conversa e expiram em quinze minutos; disponibilidade não é reserva. Não exponha detalhes de outros eventos da agenda. Use simulated para distinguir demonstração de agenda real."),
    ("preparar_agendamento", "/prepare", Proposal,
     "Preparar a reunião escolhida com slot_id de uma consulta atual, nome, e-mail do participante e assunto informados na conversa. Não invente dados. Retorna o resumo, proposal_id e o estado de confirmação. Apresente o resumo no tom do tenant e obtenha confirmação do cliente antes de chamar confirmar_agendamento em um turno posterior. Esta preparação não cria evento nem envia convite."),
    ("confirmar_agendamento", "/confirm", Reference,
     "Criar a reunião preparada somente após o cliente confirmar o resumo mostrado anteriormente. Usa proposal_id desta conversa; o serviço revalida disponibilidade. Só confirme o agendamento se status for confirmed. Se simulated=true, informe que é uma simulação sem evento na conta Google; nunca apresente como convite real. pending_verification exige consulta de estado, não uma nova proposta ou nova tentativa de criação."),
    ("consultar_agendamento", "/status", Reference,
     "Consultar a reunião desta conversa pelo proposal_id, inclusive após timeout ou confirmação incerta. Não cria nem repete eventos. Informe a data, horário e link retornados quando confirmado; um link do Meet pode ainda estar sendo preparado pelo Google. Não invente links ou confirmação. Não consulta a agenda ou dados de outras pessoas."),
    ("atualizar_participantes_reuniao", "/participants", Participants,
     "Adicionar participantes à reunião já confirmada desta conversa, preservando horário, Google Meet e os convidados existentes. Use somente e-mails fornecidos pelo cliente, sem inventar ou buscar contatos. A solicitação explícita de incluir alguém autoriza atualizar o mesmo evento, sem criar outra reunião. Para reenviar convites quando o cliente disser que não recebeu, use resend_invitations=true; emails pode ser vazio para manter os convidados. Não prometa entrega na caixa de entrada: invitations_requested informa apenas que o Google aceitou solicitar o envio. pending_verification não autoriza repetir a alteração nem criar outra reunião.")]


def contracts(roles, editor_roles=()):
    return [{"name": name, "path": path, "description": description, "roles": roles,
             "parameters": model.model_json_schema()} for name, path, model, description in DEFINITIONS] + [
        {"name":name,"path":path,"description":description,"roles":list(editor_roles),
         "parameters":model.model_json_schema()} for name,path,model,description in EDITOR_DEFINITIONS if editor_roles]
