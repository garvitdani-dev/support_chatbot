import json
from dataclasses import replace
from types import SimpleNamespace
import openai
from app import agent
from app.config import settings

class FakeResponses:
    def __init__(self): self.calls=[]
    def create(self,**kwargs):
        self.calls.append(kwargs)
        n=len(self.calls)
        usage=SimpleNamespace(input_tokens=10,output_tokens=5)
        if n==1:
            call=SimpleNamespace(type='function_call',name='search_documents',arguments='{"query":"rate changes"}',call_id='c1')
            return SimpleNamespace(id='r1',output=[call],output_text='',usage=usage)
        if n==2:
            assert kwargs['store'] is False
            assert kwargs['input'][-1]['type']=='function_call_output'
            call=SimpleNamespace(type='function_call',name='get_document_section',arguments='{"document_id":"doc1","location":null}',call_id='c2')
            return SimpleNamespace(id='r2',output=[call],output_text='',usage=usage)
        if n==3:
            assert kwargs['input'][-1]['type']=='function_call_output'
            return SimpleNamespace(id='r3',output=[],output_text=json.dumps({'answer':'Approval is required.','status':'verified','source_ids':['chunk1']}),usage=usage)
        return SimpleNamespace(id='r4',output=[],output_text='{"supported":true,"conflict":false}',usage=usage)

def test_iterative_retrieval_and_source_verification(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','fake')
    config=replace(settings,openai_model='test-model',embedding_model='test-embedding')
    monkeypatch.setattr(agent,'settings',config)
    responses=FakeResponses()
    monkeypatch.setattr(openai,'OpenAI',lambda **kwargs:SimpleNamespace(responses=responses))
    evidence={'chunk_id':'chunk1','document_id':'doc1','filename':'rate.docx','location':'Rate changes','content_type':'section','content':'Approval is required.','version':1}
    monkeypatch.setattr(agent,'_execute',lambda tenant,name,args:[evidence])
    result=agent.answer('alpha','session1','Can the rate change?',[])
    assert result['status']=='verified'
    assert result['sources'][0]['filename']=='rate.docx'
    assert result['trace']['iterations']==3
    assert [x['name'] for x in result['trace']['calls']]==['search_documents','get_document_section']
    assert len(responses.calls)==4
