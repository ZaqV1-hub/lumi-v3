"""Native screens; no HTML embedding or simulator token is exposed."""


def chat_layout():
    return {'version':'7.1','data_api_version':'3.0','routing_model':{'CHAT':['FINISH'],'FINISH':[]},
        'screens':[
            {'id':'CHAT','title':'Conversa','data':{
                'history':{'type':'string','__example__':'Como posso ajudar?'},
                'nonce':{'type':'string','__example__':'example-turn'},
                'can_ask':{'type':'boolean','__example__':True},
                'question_init':{'type':'string','__example__':''},
                'action_label':{'type':'string','__example__':'Enviar mensagem'},
            },'layout':{'type':'SingleColumnLayout','children':[
                {'type':'TextCaption','text':'Escreva abaixo para conversar. A resposta aparece nesta tela.'},
                {'type':'TextBody','text':'${data.history}','markdown':True},
                {'type':'EmbeddedLink','text':'Encerrar atendimento','on-click-action':{
                    'name':'navigate','next':{'type':'screen','name':'FINISH'},'payload':{}}},
                {'type':'Form','name':'chat_form','init-values':{'question':'${data.question_init}'},'children':[
                    {'type':'TextArea','name':'question','label':'Digite sua mensagem','max-length':2000,
                        'visible':'${data.can_ask}','required':True},
                    {'type':'Footer','label':'${data.action_label}','on-click-action':{
                        'name':'data_exchange','payload':{'question':'${form.question}',
                            'nonce':'${data.nonce}','operation':'ask'}}},
                ]},
            ]}},
            {'id':'FINISH','title':'Encerrar teste','terminal':True,'data':{},'layout':{
                'type':'SingleColumnLayout','children':[
                    {'type':'TextBody','text':'O histórico permanece salvo no atendimento. Você pode fechar esta tela.'},
                    {'type':'Footer','label':'Fechar','on-click-action':{'name':'complete','payload':{}}},
                ]}},
        ]}
