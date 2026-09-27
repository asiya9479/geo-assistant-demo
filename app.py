import streamlit as st
from pathlib import Path
import sqlite3, re
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
    stopwords = {"hansı", "hansılardır", "nədir", "necə", "və", "ilə", "olan", "üçün", "bu", "bir", "əsas", "haqqında", "harada", "olub", "edir"}
    words = {w[:5] for w in re.findall(r"\w+", q.casefold()) if len(w)>3 and w not in stopwords}
    con = db()
    rows = con.execute("SELECT name,text,access FROM documents").fetchall()
    con.close()
    allowed = {"Tələbə/Təcrübəçi":{"Açıq"},
               "Geoloq/Alim":{"Açıq","Layihə"},
               "Rəhbərlik/Admin":{"Açıq","Layihə","Məxfi"}}[role]
    hits=[]
    for name, text, access in rows:
        if access not in allowed: continue
        # PDF-dəki cümlələri balına görə seç; cavab mətnini dəyişdirmə.
        sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text or "")
        ranked=[]
        for sentence in sentences:
            sentence = " ".join(sentence.split())
            if len(sentence) < 25: continue
            terms = re.findall(r"\w+", sentence.casefold())
            matched = sum(any(term.startswith(word) for term in terms) for word in words)
            if matched:
                ranked.append((matched, sentence[:900]))
        if ranked:
            ranked.sort(key=lambda x: (-x[0], len(x[1])))
            selected = ranked[:3]
            hits.append((sum(x[0] for x in selected), name, "\n\n".join(x[1] for x in selected), access))
    return sorted(hits, reverse=True)[:5]

st.title("🌍 Geo Assistant")
st.caption("Rəqəmsal Geoloji Arxiv və Analiz Köməkçisi")

with st.sidebar:
    st.header("İstifadəçi")
    role=st.selectbox("Rol", ["Tələbə/Təcrübəçi","Geoloq/Alim","Rəhbərlik/Admin"])

tab_chat, tab_docs, tab_map, tab_admin = st.tabs(["🔎 Sənəddən soruş","📚 Arxiv","🗺️ GIS Xəritəsi","⚙️ İdarəetmə"])

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
        if hits:
            st.markdown("### PDF-də tapılan hissələr")
            for score,name,snippet,access in hits:
                st.markdown(f"**Mənbə: {name}**")
                st.info(snippet)
        else:
            st.warning("Bu sual üçün sənədlərdə uyğun mətn tapılmadı. PDF skandırsa, mətni oxumaq üçün OCR lazımdır.")

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
