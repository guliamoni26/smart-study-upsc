
import os, re, json, sqlite3, uuid
from datetime import date, timedelta
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import fitz
from openai import OpenAI

ROOT=Path(__file__).parent
DB=ROOT/"smartstudy.db"
UPLOADS=ROOT/"uploads"
UPLOADS.mkdir(exist_ok=True)
app=FastAPI(title="Smart Study UPSC Portal")
app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS docs(id TEXT PRIMARY KEY,name TEXT,subject TEXT,text TEXT,created TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,doc_id TEXT,subject TEXT,stage TEXT,topic TEXT,payload TEXT,created TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,question_id TEXT,subject TEXT,topic TEXT,correct INTEGER,chosen TEXT,created TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY,title TEXT,subject TEXT,content TEXT,created TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,topic TEXT,subject TEXT,due TEXT,interval_days INTEGER,done INTEGER DEFAULT 0)""")
    c.commit(); return c

class GenerateRequest(BaseModel):
    doc_id:str
    stage:str="Prelims"
    count:int=10
    difficulty:str="Mixed"
    question_type:str="UPSC-style"
class AttemptRequest(BaseModel):
    question_id:str
    chosen:str
class NoteRequest(BaseModel):
    title:str
    subject:str
    content:str
class RevisionRequest(BaseModel):
    topic:str
    subject:str
    due:str|None=None

def client():
    if not os.getenv("OPENAI_API_KEY"): raise HTTPException(503,"Set OPENAI_API_KEY in your environment to enable AI question generation.")
    return OpenAI()

@app.get("/",response_class=HTMLResponse)
def home(): return (ROOT/"static/index.html").read_text(encoding="utf-8")

@app.post("/api/upload")
async def upload_pdf(file:UploadFile=File(...),subject:str=Form("General")):
    if not file.filename.lower().endswith(".pdf"): raise HTTPException(400,"Please upload a PDF.")
    raw=await file.read()
    if len(raw)>25*1024*1024: raise HTTPException(413,"PDF must be 25 MB or smaller.")
    try:
        doc=fitz.open(stream=raw,filetype="pdf")
        pages=[]
        for i,p in enumerate(doc):
            t=p.get_text("text")
            if t.strip(): pages.append(f"[PAGE {i+1}]\n{t}")
        extracted="\n\n".join(pages)
    except Exception: raise HTTPException(400,"Could not read this PDF. It may be encrypted or damaged.")
    if len(extracted.strip())<100: raise HTTPException(422,"Very little selectable text was found. OCR for scanned PDFs is not included in this first release.")
    did=str(uuid.uuid4())
    c=db(); c.execute("INSERT INTO docs VALUES(?,?,?,?,?)",(did,file.filename,subject,extracted,date.today().isoformat())); c.commit(); c.close()
    return {"id":did,"name":file.filename,"subject":subject,"pages":len(pages),"characters":len(extracted)}

@app.get("/api/docs")
def docs():
    c=db(); rows=c.execute("SELECT id,name,subject,created,length(text) chars FROM docs ORDER BY created DESC").fetchall(); c.close()
    return [dict(r) for r in rows]

@app.post("/api/generate")
def generate(req:GenerateRequest):
    if req.stage not in ("Prelims","Mains"): raise HTTPException(400,"Stage must be Prelims or Mains.")
    if not 1<=req.count<=25: raise HTTPException(400,"Choose 1–25 questions.")
    c=db(); row=c.execute("SELECT * FROM docs WHERE id=?",(req.doc_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,"Document not found.")
    source=row["text"][:42000]
    prompt=f"""You are an expert UPSC Civil Services examination question setter. Use ONLY the supplied study extract as the factual source. Do not invent facts. Create {req.count} {req.stage} questions, difficulty {req.difficulty}. Question style: {req.question_type}.
For Prelims, produce four-option single-best-answer UPSC-style MCQs, including statement-based questions where suitable. For Mains, produce analytical 10/15-mark prompts with word limit and a concise evaluation rubric.
Return STRICT JSON: {{ "questions":[{{"topic":"specific syllabus topic","question":"...","options":["A...","B...","C...","D..."],"answer":"A","explanation":"...","difficulty":"Easy|Moderate|Difficult","page_reference":"page number or Not specified","marks":10,"word_limit":150,"rubric":["..."]}}] }}.
For Mains, options can be []. Keep answer as option letter for Prelims. Ensure the answer is supported by the extract. Avoid ambiguous questions.
SOURCE EXTRACT:
{source}"""
    try:
        response=client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-4.1-mini"),input=prompt)
        content=response.output_text
        match=re.search(r"\{.*\}",content,re.S)
        data=json.loads(match.group(0) if match else content)
        qs=data.get("questions",[])
        if not qs: raise ValueError("No questions returned")
    except HTTPException: raise
    except Exception as e: c.close(); raise HTTPException(502,f"AI generation failed: {str(e)[:300]}")
    ids=[]
    for q in qs:
        qid=str(uuid.uuid4()); ids.append(qid)
        c.execute("INSERT INTO questions VALUES(?,?,?,?,?,?,?)",(qid,row["id"],row["subject"],req.stage,q.get("topic","General"),json.dumps(q,ensure_ascii=False),date.today().isoformat()))
    c.commit(); c.close()
    return {"questions":[{"id":qid,**q} for qid,q in zip(ids,qs)]}

@app.get("/api/questions")
def questions(stage:str|None=None):
    c=db(); sql="SELECT * FROM questions"; args=[]
    if stage: sql+=" WHERE stage=?"; args=[stage]
    sql+=" ORDER BY created DESC"
    rows=c.execute(sql,args).fetchall(); c.close()
    out=[]
    for r in rows: out.append({"id":r["id"],"subject":r["subject"],"stage":r["stage"],**json.loads(r["payload"])})
    return out

@app.post("/api/attempt")
def attempt(req:AttemptRequest):
    c=db(); r=c.execute("SELECT * FROM questions WHERE id=?",(req.question_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,"Question not found")
    q=json.loads(r["payload"]); correct=req.chosen.strip().upper()==q.get("answer","").strip().upper()
    c.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?)",(str(uuid.uuid4()),req.question_id,r["subject"],q.get("topic","General"),int(correct),req.chosen,date.today().isoformat()))
    c.commit(); c.close()
    return {"correct":correct,"answer":q.get("answer"),"explanation":q.get("explanation",""),"topic":q.get("topic","General")}

@app.get("/api/analytics")
def analytics():
    c=db(); rows=c.execute("SELECT subject,topic,COUNT(*) n,SUM(correct) correct FROM attempts GROUP BY subject,topic").fetchall()
    total=c.execute("SELECT COUNT(*) n,SUM(correct) c FROM attempts").fetchone()
    wrong=c.execute("SELECT q.payload,a.chosen FROM attempts a JOIN questions q ON q.id=a.question_id WHERE a.correct=0 ORDER BY a.created DESC LIMIT 20").fetchall()
    c.close()
    return {"total":total["n"] or 0,"correct":total["c"] or 0,"accuracy":round(100*(total["c"] or 0)/(total["n"] or 1)) if total["n"] else 0,
            "topics":[dict(x) for x in rows],"mistakes":[{"question":json.loads(x["payload"]).get("question"),"chosen":x["chosen"],"answer":json.loads(x["payload"]).get("answer")} for x in wrong]}

@app.post("/api/notes")
def save_note(n:NoteRequest):
    c=db(); nid=str(uuid.uuid4()); c.execute("INSERT INTO notes VALUES(?,?,?,?,?)",(nid,n.title,n.subject,n.content,date.today().isoformat())); c.commit(); c.close(); return {"id":nid}
@app.get("/api/notes")
def notes():
    c=db(); r=c.execute("SELECT * FROM notes ORDER BY created DESC").fetchall(); c.close(); return [dict(x) for x in r]
@app.delete("/api/notes/{nid}")
def delete_note(nid:str):
    c=db(); c.execute("DELETE FROM notes WHERE id=?",(nid,)); c.commit(); c.close(); return {"ok":True}

@app.post("/api/revisions")
def add_revision(r:RevisionRequest):
    c=db(); rid=str(uuid.uuid4()); due=r.due or date.today().isoformat(); c.execute("INSERT INTO revisions(id,topic,subject,due) VALUES(?,?,?,?)",(rid,r.topic,r.subject,due)); c.commit(); c.close(); return {"id":rid}
@app.get("/api/revisions")
def revisions():
    c=db(); r=c.execute("SELECT * FROM revisions WHERE done=0 ORDER BY due").fetchall(); c.close(); return [dict(x) for x in r]
@app.post("/api/revisions/{rid}/done")
def done_revision(rid:str):
    c=db(); r=c.execute("SELECT * FROM revisions WHERE id=?",(rid,)).fetchone()
    if not r: c.close(); raise HTTPException(404,"Revision not found")
    # spaced repeat: mark complete and create next interval (1,3,7,14,30)
    interval=r["interval_days"] or 1
    next_due=date.fromisoformat(r["due"])+timedelta(days=interval)
    c.execute("UPDATE revisions SET done=1 WHERE id=?",(rid,))
    c.execute("INSERT INTO revisions(id,topic,subject,due,interval_days) VALUES(?,?,?,?,?)",(str(uuid.uuid4()),r["topic"],r["subject"],next_due.isoformat(),min(interval*2,30)))
    c.commit(); c.close(); return {"next_due":next_due.isoformat(),"interval_days":min(interval*2,30)}

@app.get("/api/health")
def health(): return {"status":"ok","ai_enabled":bool(os.getenv("OPENAI_API_KEY"))}
