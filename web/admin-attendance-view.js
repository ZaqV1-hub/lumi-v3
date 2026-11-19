function attendanceMarkup() {
  return `<div class="attendance-settings"><svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="att-i-grid" viewBox="0 0 20 20"><rect x="2.5" y="2.5" width="6.5" height="6.5" rx="2"/><rect x="11" y="2.5" width="6.5" height="6.5" rx="2"/><rect x="2.5" y="11" width="6.5" height="6.5" rx="2"/><rect x="11" y="11" width="6.5" height="6.5" rx="2"/></symbol>
<symbol id="att-i-chat" viewBox="0 0 20 20"><path d="M3.5 5.5a2 2 0 012-2h9a2 2 0 012 2v6a2 2 0 01-2 2H9l-3.5 3v-3a2 2 0 01-2-2z"/></symbol>
<symbol id="att-i-sliders" viewBox="0 0 20 20"><path d="M3 5h14M3 10h9M3 15h12"/></symbol>
<symbol id="att-i-bars" viewBox="0 0 20 20"><path d="M5 16V9M10 16V4M15 16v-5"/></symbol>
<symbol id="att-i-menu" viewBox="0 0 20 20"><path d="M3 6h14M3 10h14M3 14h14"/></symbol>
<symbol id="att-i-check" viewBox="0 0 20 20"><path d="M4.5 10.5l3.5 3.5 7.5-8"/></symbol>
<symbol id="att-i-copy" viewBox="0 0 20 20"><rect x="7" y="7" width="9.5" height="9.5" rx="2"/><path d="M13 7V5.5A2 2 0 0011 3.5H5.5a2 2 0 00-2 2V11a2 2 0 002 2H7"/></symbol>
<symbol id="att-i-alert" viewBox="0 0 20 20"><path d="M10 3.5l7 12.5H3z"/><path d="M10 8.5v3.2M10 14v.1"/></symbol>
</defs></svg>        <!-- 1. Horário da equipe -->
        <section class="card" id="cardTeam" aria-labelledby="hTeam">
          <div class="card-h">
            <div><h2 id="hTeam">Horário de atendimento da equipe</h2><p>A assistente continua atendendo fora do horário. Os pedidos de atendente são avisados à equipe na próxima abertura.</p></div>
            <button class="sw" id="swTeam" type="button" role="switch" aria-checked="true" aria-labelledby="hTeam"><i></i></button>
          </div>
          <div class="card-b">
            <div class="now" id="now" role="status"><span class="dot"></span><div><b id="nowT"></b><span id="nowD"></span></div><div class="clk num" id="nowC"></div></div>
            <div class="dim" id="teamBody" style="display:flex;flex-direction:column;gap:18px">
              <div class="field">
                <label for="tz">Fuso horário</label>
                <select class="select" id="tz">
                  <option value="America/Sao_Paulo">Brasília · America/Sao_Paulo</option>
                  <option value="America/Manaus">Manaus · America/Manaus</option>
                  <option value="America/Cuiaba">Cuiabá · America/Cuiaba</option>
                  <option value="America/Fortaleza">Fortaleza · America/Fortaleza</option>
                  <option value="America/Rio_Branco">Rio Branco · America/Rio_Branco</option>
                  <option value="America/Noronha">Fernando de Noronha · America/Noronha</option>
                </select>
              </div>
              <div>
                <span class="sec-t">Dias e horários</span>
                <div class="tools" style="margin-bottom:12px" role="group" aria-label="Atalhos de horário">
                  <button class="chip" type="button" data-preset="com">Seg a sex, 9h às 17h</button>
                  <button class="chip" type="button" data-preset="all">Todos os dias, 8h às 18h</button>
                  <button class="chip" type="button" data-preset="24">24 horas</button>
                  <button class="chip" type="button" data-preset="copy"><svg class="ic" style="width:15px;height:15px"><use href="#att-i-copy"/></svg>Copiar segunda para seg a sex</button>
                </div>
                <div class="sched" id="sched" role="group" aria-label="Horário por dia da semana"></div>
                <div class="warn" id="warnDays" hidden style="margin-top:12px"><svg class="ic"><use href="#att-i-alert"/></svg><span>Marque pelo menos um dia de atendimento.</span></div>
              </div>
              <div class="summary" id="summary" aria-label="Resumo do horário"></div>
            </div>
          </div>
        </section>

        <!-- 2. Aviso de espera -->
        <section class="card" id="cardWait" aria-labelledby="hWait">
          <div class="card-h">
            <div><h2 id="hWait">Aviso quando ninguém responde</h2><p>Avisa a equipe quando um cliente pediu um atendente e ninguém assumiu a conversa.</p></div>
            <button class="sw" id="swWait" type="button" role="switch" aria-checked="true" aria-labelledby="hWait"><i></i></button>
          </div>
          <div class="card-b">
            <div class="dim" style="display:flex;flex-direction:column;gap:18px" id="waitBody">
              <div>
                <span class="sec-t" id="lblWait">Tempo de espera</span>
                <div class="wait-row">
                  <div class="stepper" role="group" aria-labelledby="lblWait">
                    <button type="button" id="wMinus" aria-label="Diminuir 1 minuto">−</button>
                    <input id="wait" type="text" inputmode="numeric" maxlength="3" aria-label="Minutos de espera">
                    <button type="button" id="wPlus" aria-label="Aumentar 1 minuto">+</button>
                  </div>
                  <span class="u">minutos</span>
                  <div class="chips" id="waitChips" role="group" aria-label="Valores comuns"></div>
                </div>
                <p class="hint" id="waitErr" style="margin-top:8px"></p>
              </div>
              <div>
                <span class="sec-t">Quando avisar</span>
                <div class="rcs" id="modes" role="radiogroup" aria-label="Quando aplicar o aviso">
                  <label class="rc" data-m="waiting"><input type="radio" name="mode" value="waiting"><div><b>Somente enquanto aguarda alguém assumir</b><span>Avisa quando o pedido de atendente passa do tempo sem ninguém assumir.</span></div></label>
                  <label class="rc" data-m="always"><input type="radio" name="mode" value="always"><div><b>Sempre que o cliente ficar sem resposta</b><span>Avisa também quando o cliente escreve de novo e o atendente não responde no prazo.</span></div></label>
                </div>
              </div>
              <div>
                <span class="sec-t">Como funciona</span>
                <ol class="flow" id="flow">
                  <li><span><b>O cliente pede</b> para falar com um atendente.</span></li>
                  <li><span>Passam <b id="fMin">10 minutos</b> sem ninguém assumir.</span></li>
                  <li><span><b>A equipe é avisada</b> pelos canais de atendimento.</span></li>
                  <li><span>O pedido <b>fica na fila</b> e a assistente continua ajudando.</span></li>
                </ol>
              </div>
              <ul class="notes">
                <li><svg class="ic"><use href="#att-i-check"/></svg>Se o atendente já respondeu e o cliente não voltou a perguntar, não há aviso.</li>
                <li><svg class="ic"><use href="#att-i-check"/></svg>Ligações em andamento são preservadas.</li>
              </ul>
            </div>
          </div>
        </section>

        <!-- 3. Telefone -->
        <section class="card" aria-labelledby="hPh">
          <div class="card-h">
            <div><h2 id="hPh">Telefone do cliente</h2><p>Pedir autorização para exibir o telefone à equipe no WhatsApp.</p></div>
            <button class="sw" id="swPhone" type="button" role="switch" aria-checked="true" aria-labelledby="hPh"><i></i></button>
          </div>
          <div class="card-b">
            <p style="font-size:13.5px;color:var(--ink-2)">O cliente escolhe pelos botões da mensagem. O número só aparece no perfil depois de autorizar.</p>
            <div class="out" id="phoneOut">
              <div><b>Se o cliente autorizar</b>O número aparece no perfil da conversa.</div>
              <div><b>Se o cliente recusar</b>O atendimento segue normalmente, sem mostrar o número.</div>
            </div>
          </div>
        </section>

      <div class="savebar"><div class="in">
          <div class="sv-s" id="svS" role="status">Tudo salvo</div>
          <div class="sv-a"><button class="btn btn-ghost" id="discard" type="button" hidden>Descartar alterações</button><button class="btn btn-primary" id="save" type="button" disabled>Salvar regras de atendimento</button></div>
        </div></div>
</div>`;
}
