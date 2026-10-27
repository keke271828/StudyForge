"""Inventory and preserve app-owned visible-copy sources, excluding vendors/data."""
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/ui-copy-audit-20261026-2'
CHINESE=re.compile(r'[\u4e00-\u9fff]')


def js_strings(text):
    """Read literals without treating quote characters inside regex as strings."""
    def literal(index):
        quote=text[index];start=index;index+=1
        while index<len(text):
            if text[index]=='\\':index+=2;continue
            if text[index]==quote:return index+1
            if quote=='`' and text.startswith('${',index):
                index=expression(index+2);continue
            index+=1
        return len(text)
    def slash(index):
        if text.startswith('//',index):
            end=text.find('\n',index);return len(text) if end<0 else end
        if text.startswith('/*',index):
            end=text.find('*/',index+2);return len(text) if end<0 else end+2
        previous=text[:index].rstrip()
        if previous and previous[-1] not in '=(:,![{?;|&':return index+1
        index+=1;bracket=False
        while index<len(text) and text[index]!='\n':
            if text[index]=='\\':index+=2;continue
            if text[index]=='[':bracket=True
            elif text[index]==']':bracket=False
            elif text[index]=='/' and not bracket:
                index+=1
                while index<len(text) and text[index].isalpha():index+=1
                return index
            index+=1
        return index
    def expression(index):
        depth=1
        while index<len(text):
            char=text[index]
            if char in "'\"`":index=literal(index);continue
            if char=='/':index=slash(index);continue
            if char=='{':depth+=1
            elif char=='}':
                depth-=1
                if not depth:return index+1
            index+=1
        return index
    index=0
    while index<len(text):
        if text[index] in "'\"`":
            end=literal(index);yield index,text[index+1:end-1];index=end
        elif text[index]=='/':index=slash(index)
        else:index+=1


class Texts(HTMLParser):
    def __init__(self):super().__init__();self.items=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if not self.skip:
            for key,value in attrs:
                if key in ('title','placeholder','aria-label','alt') and value and CHINESE.search(value):
                    self.items.append({'line':self.getpos()[0],'kind':key,'text':value})
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,value):
        if not self.skip and CHINESE.search(value):
            self.items.append({'line':self.getpos()[0],'kind':'text','text':value.strip()})


def inventory(path):
    text=path.read_text(encoding='utf-8');items=[]
    if path.suffix=='.html':
        parser=Texts();parser.feed(text);items=parser.items
    else:
        for start,value in js_strings(text):
            if not CHINESE.search(value):continue
            value=unescape(re.sub(r'<[^>]+>',' ',value))
            items.append({'line':text.count('\n',0,start)+1,'kind':'literal','text':value})
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'items':items,'chinese_literals':len(items)}


def main():
    if OUT.exists():raise SystemExit('Preserve the initial inventory; do not overwrite it.')
    OUT.mkdir();paths=sorted([p for folder in ('web','desktop') for p in (ROOT/folder).rglob('*')
                            if p.suffix in ('.html','.js','.json') and 'vendor' not in p.parts])
    data=[inventory(path) for path in paths]
    for path in paths:
        target=OUT/'before'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    (OUT/'before.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in data:
        if not row['items']:continue
        target=OUT/'inventory'/(row['path'].replace('/','__')+'.txt');target.parent.mkdir(exist_ok=True)
        target.write_text('\n'.join(f"{item['line']}: "+re.sub(r'\s+',' ',item['text']) for item in row['items']),encoding='utf-8')
    print(json.dumps({'files':len(paths),'files_with_chinese':sum(bool(row['items']) for row in data),
                      'chinese_literals':sum(row['chinese_literals'] for row in data),'output':str(OUT)},ensure_ascii=False))


if __name__=='__main__':main()
