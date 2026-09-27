import streamlit as st
from pathlib import Path
import sqlite3, re, requests
import pandas as pd
from pypdf import PdfReader
from docx import Document
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Geo Assistant", page_icon="🌍", layout="wide")
DATA = Path("data"); DATA.mkdir(exist_ok=True)
UPLOADS = DATA / "uploads"; UPLOADS.mkdir(exist_ok=True)
DB = DATA / "geo.db"

def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS documents(
        id INTEGER PRIMARY KEY, name TEXT UNIQUE, text TEXT, access TEXT DEFAULT 'Açıq')""")
    c.execute("""CREATE TABLE IF NOT EXISTS wells(
        id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL, depth REAL, notes TEXT)""")
    c.commit()
    return c

def extract(path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if ext == ".docx":
        return "\n".join(p.text for p in Document(str(path)).paragraphs)
    if ext in [".txt", ".md"]:
        return path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".csv":
        return pd.read_csv(path).to_csv(index=False)
    if ext in [".xlsx", ".xls"]:
        x = pd.ExcelFile(path)
        return "\n".join(pd.read_excel(path, sheet_name=s).to_csv(index=False) for s in x.sheet_names)
    return ""

def search_docs(q, role):
    words = [w.lower() for w in re.findall(r"\w+", q) if len(w)>2]
    con = db()
    rows = con.execute("SELECT name,text,access FROM documents").fetchall()
    con.close()
    allowed = {"Tələbə/Təcrübəçi":{"Açıq"},
               "Geoloq/Alim":{"Açıq","Layihə"},
               "Rəhbərlik/Admin":{"Açıq","Layihə","Məxfi"}}[role]
    hits=[]
    for name, text, access in rows:
        if access not in allowed: continue
        low=text.lower()
        score=sum(low.count(w) for w in words)
        if score:
            pos=min([low.find(w) for w in words if low.find(w)>=0] or [0])
            snippet=text[max(0,pos-500):pos+1800]
            hits.append((score,name,snippet,access))
    return sorted(hits, reverse=True)[:5]

def ask_ai(question, hits, api_url, api_key, model):
    context="\n\n".join(f"MƏNBƏ: {h[1]}\n{h[2]}" for h in hits)
    if not api_key or not api_url:
        return "GPT bağlantısı üçün sol paneldə API açarını daxil edin."
    if hits:
        prompt=f"""Sən Geo Assistant-san. Aşağıdakı arxiv mənbələrinə əsaslanaraq Azərbaycan dilində cavab ver.
Mənbənin adını göstər. Mənbələrdə cavab yoxdursa bunu açıq de; fakt uydurma.

SUAL: {question}

ARXİV:
{context}"""
    else:
        prompt=f"""Sən Geo Assistant-san. İstifadəçinin sualına Azərbaycan dilində aydın cavab ver.
Bu sual üçün arxiv mənbəsi tapılmayıb. Arxiv məlumatı varmış kimi iddia etmə.

SUAL: {question}"""
    url=api_url.rstrip("/") + "/chat/completions"
    r=requests.post(url, headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
        json={"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0.1}, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

st.title("🌍 Geo Assistant")
st.caption("Rəqəmsal Geoloji Arxiv və Analiz Köməkçisi")

with st.sidebar:
    st.header("İstifadəçi")
    role=st.selectbox("Rol", ["Tələbə/Təcrübəçi","Geoloq/Alim","Rəhbərlik/Admin"])
    st.divider()
    st.header("AI bağlantısı")
    api_url=st.text_input("OpenAI-compatible API URL", "https://api.openai.com/v1")
    api_key=st.text_input("API açarı", type="password")
    model=st.text_input("Model", "gpt-4.1-mini")
    st.caption("Açar saxlanmır; yalnız cari sessiyada istifadə olunur.")

tab_chat, tab_docs, tab_map, tab_admin = st.tabs(["💬 AI Çat","📚 Arxiv","🗺️ GIS Xəritəsi","⚙️ İdarəetmə"])

with tab_docs:
    st.subheader("Geoloji sənədlər")
    access=st.selectbox("Sənədin giriş səviyyəsi", ["Açıq","Layihə","Məxfi"])
    uploads=st.file_uploader("PDF, DOCX, TXT, CSV və XLSX yükləyin",
        type=["pdf","docx","txt","md","csv","xlsx"], accept_multiple_files=True)
    if st.button("Arxivə əlavə et", disabled=not uploads):
        con=db()
        for f in uploads:
            p=UPLOADS/f.name
            p.write_bytes(f.getbuffer())
            try:
                txt=extract(p)
                con.execute("INSERT OR REPLACE INTO documents(name,text,access) VALUES(?,?,?)",(f.name,txt,access))
                st.success(f"{f.name} əlavə edildi — {len(txt):,} simvol.")
            except Exception as e: st.error(f"{f.name}: {e}")
        con.commit(); con.close()
    con=db()
    docs=con.execute("SELECT name,access,length(text) FROM documents ORDER BY name").fetchall()
    con.close()
    if docs: st.dataframe(pd.DataFrame(docs,columns=["Sənəd","Giriş","Mətn simvolu"]),use_container_width=True)

with tab_chat:
    st.subheader("Arxivdən soruş")
    q=st.text_area("Sual", placeholder="Məsələn: Bu ərazidə əvvəllər hansı seysmik tədqiqatlar aparılıb?")
    if st.button("Cavab tap", type="primary", disabled=not q.strip()):
        hits=search_docs(q,role)
        try: answer=ask_ai(q,hits,api_url,api_key,model)
        except Exception as e: answer=f"AI bağlantısında xəta: {e}"
        st.markdown("### Cavab")
        st.write(answer)
        if hits:
            st.markdown("### Mənbələr")
            for score,name,snippet,access in hits:
                with st.expander(f"{name} · {access} · uyğunluq {score}"):
                    st.text(snippet[:2200])
        else:
            st.caption("Bu cavab institut arxivində tapılmış sənədə əsaslanmır.")

with tab_map:
    st.subheader("GIS və quyu xəritəsi")
    if role != "Tələbə/Təcrübəçi":
        with st.expander("Quyu nöqtəsi əlavə et"):
            c1,c2,c3=st.columns(3)
            name=c1.text_input("Quyu adı")
            lat=c2.number_input("Enlik", value=40.4093, format="%.6f")
            lon=c3.number_input("Uzunluq", value=49.8671, format="%.6f")
            depth=st.number_input("Dərinlik (m)", min_value=0.0)
            notes=st.text_input("Qeyd")
            if st.button("Quyunu əlavə et") and name:
                con=db(); con.execute("INSERT INTO wells(name,lat,lon,depth,notes) VALUES(?,?,?,?,?)",(name,lat,lon,depth,notes)); con.commit(); con.close()
    con=db(); wells=con.execute("SELECT name,lat,lon,depth,notes FROM wells").fetchall(); con.close()
    m=folium.Map(location=[40.4093,49.8671],zoom_start=7,tiles="OpenStreetMap")
    for n,la,lo,d,no in wells:
        folium.Marker([la,lo],tooltip=n,popup=f"{n}<br>Dərinlik: {d} m<br>{no or ''}").add_to(m)
    st_folium(m,width=None,height=600)

with tab_admin:
    st.subheader("Sistem vəziyyəti")
    if role!="Rəhbərlik/Admin":
        st.info("Bu bölmə yalnız Rəhbərlik/Admin roluna açıqdır.")
    else:
        con=db()
        dc=con.execute("SELECT count(*) FROM documents").fetchone()[0]
        wc=con.execute("SELECT count(*) FROM wells").fetchone()[0]
        con.close()
        a,b=st.columns(2); a.metric("Arxiv sənədləri",dc); b.metric("Quyular",wc)
        st.warning("Demo rol seçimi real autentifikasiya deyil. İstehsal versiyasında Windows/LDAP və ya ayrıca giriş sistemi qurulmalıdır.")
