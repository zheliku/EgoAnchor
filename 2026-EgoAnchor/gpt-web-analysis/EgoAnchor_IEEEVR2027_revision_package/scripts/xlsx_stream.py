from __future__ import annotations
import zipfile, xml.etree.ElementTree as ET, re
from pathlib import Path
from typing import Iterator, Dict, List, Optional, Iterable

NS_MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'

_COL_RE = re.compile(r'([A-Z]+)')

def col_to_idx(ref: str) -> int:
    m=_COL_RE.match(ref)
    if not m: return -1
    n=0
    for c in m.group(1): n=n*26+ord(c)-64
    return n-1

def sheet_map(path: str|Path) -> Dict[str,str]:
    with zipfile.ZipFile(path) as z:
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rid_to_target={r.attrib['Id']:r.attrib['Target'] for r in rels}
        out={}
        sheets=wb.find(f'{{{NS_MAIN}}}sheets')
        for s in sheets:
            name=s.attrib['name']; rid=s.attrib[f'{{{NS_REL}}}id']; target=rid_to_target[rid]
            xml_path=target.lstrip('/') if target.startswith('/') else 'xl/'+target.lstrip('/')
            out[name]=xml_path
        return out

def _cell_value(c: ET.Element):
    t=c.attrib.get('t')
    if t=='inlineStr':
        texts=[x.text or '' for x in c.iter(f'{{{NS_MAIN}}}t')]
        return ''.join(texts)
    v=c.find(f'{{{NS_MAIN}}}v')
    if v is None: return None
    txt=v.text
    if t=='b': return txt=='1'
    if t in ('str','e'): return txt
    try:
        if txt is None: return None
        if any(ch in txt for ch in '.eE'):
            return float(txt)
        return int(txt)
    except Exception:
        return txt

def iter_rows(path: str|Path, sheet_name: str, columns: Optional[Iterable[str]]=None, max_rows: Optional[int]=None) -> Iterator[Dict[str,object]]:
    sm=sheet_map(path); xml_path=sm[sheet_name]
    with zipfile.ZipFile(path) as z, z.open(xml_path) as f:
        context=ET.iterparse(f, events=('end',))
        headers: List[Optional[str]]=[]
        wanted=set(columns) if columns else None
        out_count=0
        for event, elem in context:
            if elem.tag != f'{{{NS_MAIN}}}row':
                continue
            vals={}
            maxidx=-1
            for c in elem.findall(f'{{{NS_MAIN}}}c'):
                idx=col_to_idx(c.attrib.get('r',''))
                if idx<0: continue
                vals[idx]=_cell_value(c); maxidx=max(maxidx,idx)
            if not headers:
                headers=[None]*(maxidx+1)
                for idx,val in vals.items():
                    if idx>=len(headers): headers.extend([None]*(idx+1-len(headers)))
                    headers[idx]=str(val) if val is not None else None
                elem.clear(); continue
            row={}
            for idx,val in vals.items():
                if idx<len(headers) and headers[idx]:
                    h=headers[idx]
                    if wanted is None or h in wanted:
                        row[h]=val
            if row:
                yield row; out_count+=1
                if max_rows is not None and out_count>=max_rows:
                    elem.clear(); break
            elem.clear()

def read_all(path, sheet_name, columns=None, max_rows=None):
    return list(iter_rows(path,sheet_name,columns,max_rows))
