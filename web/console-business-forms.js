function businessForm(type,row={}){
  const d=businessData,editing=!!row.id,routeAtStart=location.hash;
  const field=(name,label,value='',kind='text',extra='')=>'<label>'+label+'<input class="inp" name="'+name+'" type="'+kind+'" value="'+esc(value??'')+'" '+extra+'></label>';
  const area=(name,label,value='',limit=10000)=>'<label>'+label+'<textarea class="inp" name="'+name+'" maxlength="'+limit+'" rows="4">'+esc(value||'')+'</textarea></label>';
  const select=(name,label,options,value)=>'<label>'+label+'<select class="sel" name="'+name+'">'+options.map(([id,text])=>'<option value="'+esc(id)+'" '+(id===value?'selected':'')+'>'+esc(text)+'</option>').join('')+'</select></label>';
  const projects=d.projects.map(p=>[p.id,p.name]),contracts=d.contracts.map(c=>[c.id,c.title]);let html='',title='';
  if(type==='client'){
    title='Informações de '+d.name;
    html=field('contact_name','Pessoa de contato',row.contact_name,'text','maxlength="120"')+field('contact_email','E-mail de contato',row.contact_email,'email','maxlength="180"')+area('notes','Notas internas da Brevia',row.notes,20000);
  }else if(type==='project'){
    title=editing?'Editar projeto':'Novo projeto';
    html=field('name','Nome do projeto',row.name,'text','required maxlength="160"')+select('status','Andamento',Object.entries(businessStatus).slice(0,5),row.status||'em_andamento')+field('due_date','Prazo',row.due_date,'date')+area('summary','Resumo do projeto',row.summary,20000)+area('next_steps','Próximos passos',row.next_steps);
  }else if(type==='contract'){
    title=editing?'Editar contrato':'Novo contrato';
    html=select('project_id','Projeto',editing?projects.filter(p=>p[0]===row.project_id):projects,row.project_id)+field('title','Título do contrato',row.title,'text','required maxlength="160"')+field('kind','Tipo de contrato',row.kind,'text','required maxlength="80" placeholder="Manutenção, desenvolvimento…"')+select('status','Situação',Object.entries(businessStatus).slice(5),row.status||'ativo')+field('hours','Horas incluídas',editing?row.included_minutes/60:'','number','required min="0" max="100000" step="any"')+field('carried_hours','Horas acumuladas de ciclos anteriores',row.carried_minutes/60||0,'number','min="0" step="any"')+field('opening_hours','Horas já consumidas no saldo inicial',row.opening_used_minutes/60||0,'number','min="0" step="any"')+field('opening_as_of','Saldo inicial apurado até',row.opening_as_of,'date')+area('opening_note','Origem e explicação do saldo inicial',row.opening_note)+field('amount','Valor do contrato (R$)',row.amount_cents==null?'':row.amount_cents/100,'number','min="0" max="1000000000" step="0.01"')+field('start_date','Início da vigência',row.start_date,'date')+field('end_date','Fim da vigência',row.end_date,'date')+area('description','Escopo e observações do contrato',row.description,20000);
  }else if(type==='work'){
    title=editing?'Corrigir lançamento':'Lançar horas';
    html=select('contract_id','Contrato',contracts,row.contract_id)+field('work_date','Data da atividade',row.work_date||new Date().toLocaleDateString('sv-SE'),'date','required')+field('minutes','Tempo gasto (minutos)',row.minutes||60,'number','required min="1" max="1440" step="1"')+area('description','O que foi feito',row.description);
  }else{
    title='Registrar andamento';
    html=select('project_id','Projeto',projects,row.id)+area('content','O que mudou e como está o projeto');
  }
  const close=modal('<h2>'+esc(title)+'</h2><form id="businessForm">'+html+'<p id="businessFormError" role="alert" hidden></p><div class="acts"><button class="btn btn-ghost" type="button" id="cancelBusinessForm">Cancelar</button><button class="btn btn-primary" type="submit">Salvar</button></div></form>');
  $('#cancelBusinessForm').onclick=close;
  $('#businessForm').onsubmit=async event=>{
    event.preventDefault();const form=event.target,button=event.submitter,values=Object.fromEntries(new FormData(form));
    let path=bizPath(),method='POST',body=values;$('#businessFormError').hidden=true;button.disabled=true;
    try{
      if(type==='client'){method='PUT';}
      else if(type==='project'){path+='/projects'+(editing?'/'+row.id:'');method=editing?'PUT':'POST';body.due_date=body.due_date||null;}
      else if(type==='contract'){
        path+='/contracts'+(editing?'/'+row.id:'');method=editing?'PUT':'POST';
        const minutes=Number(body.hours)*60;
        if(Math.abs(minutes-Math.round(minutes))>0.001)throw Error('Informe horas equivalentes a um número inteiro de minutos.');
        body.included_minutes=Math.round(minutes);body.carried_minutes=Math.round(Number(body.carried_hours)*60);body.opening_used_minutes=Math.round(Number(body.opening_hours)*60);body.opening_as_of=body.opening_as_of||null;delete body.carried_hours;delete body.opening_hours;body.amount_cents=body.amount===''?null:Math.round(Number(body.amount)*100);body.start_date=body.start_date||null;body.end_date=body.end_date||null;delete body.hours;delete body.amount;
      }else if(type==='work'){path+='/work-logs'+(editing?'/'+row.id:'');method=editing?'PUT':'POST';body.minutes=Number(body.minutes);}
      else{path+='/projects/'+values.project_id+'/updates';body={content:values.content};}
      await api(path,method,body);close();toast('Informações salvas no banco.');if(location.hash===routeAtStart)await renderBusiness($('#content'),d.id);
    }catch(error){if($('#businessFormError')){$('#businessFormError').textContent=error.message;$('#businessFormError').hidden=false;}}
    finally{button.disabled=false;}
  };
}
