import json, numpy as np
from pathlib import Path
from scipy.signal import butter, filtfilt

SESS = Path("data/eval/20260707_122900_controller_right")
jl = next(SESS.glob("*_unity_output.jsonl"))

rows=[]
for line in jl.read_text(encoding="utf-8").splitlines():
    if not line.strip(): continue
    r=json.loads(line)
    if r.get("rq1_metric")!="static_observation": continue
    if not r.get("gt_pose_valid"): continue
    rows.append(r)

t0=min(r["render_mono_ms"] for r in rows)
print("static seg n=",len(rows),"dur",round((max(r['render_mono_ms'] for r in rows)-t0)/1000,1))

def highpass(sig,dt,cutoff=1.0):
    work=np.asarray(sig,float)
    if work.ndim==1: work=work[:,None]; sq=True
    else: sq=False
    nyq=0.5/dt; nc=min(0.99,cutoff/nyq)
    b,a=butter(2,nc,btype="highpass")
    filt=filtfilt(b,a,work,axis=0)
    return filt[:,0] if sq else filt

def rms(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]
    return float(np.sqrt(np.mean(x**2))) if x.size else np.nan

def relq(a,b):
    # relative rotation angle deg between quats a,b (x,y,z,w)
    a=np.asarray(a,float); b=np.asarray(b,float)
    d=abs(np.dot(a,b)); d=min(1.0,d)
    return 2*np.degrees(np.arccos(d))

def compute(window):
    s,e=window
    for lab in ["Full","No-StaticLock"]:
        sub=[]
        for r in rows:
            rel=(r["render_mono_ms"]-t0)/1000.0
            if not (s<=rel<e): continue
            v=next((x for x in r["variants"] if x["label"]==lab),None)
            if v is None or not v.get("has_output_pose"): continue
            sub.append((r["render_mono_ms"],np.array(r["gt_pos"],float),
                        np.array(v["output_pos"],float),np.array(v["output_rot"],float)))
        sub.sort(key=lambda x:x[0])
        tm=np.array([x[0] for x in sub])
        gt=np.vstack([x[1] for x in sub])
        op=np.vstack([x[2] for x in sub])
        orot=np.vstack([x[3] for x in sub])
        # static mask by GT speed
        ts=tm*0.001; dt=np.diff(ts); dt[dt<=1e-9]=np.nan
        stepv=np.linalg.norm(np.diff(gt,axis=0),axis=1)/dt
        speed=np.empty(len(sub)); speed[1:]=stepv; speed[0]=stepv[0] if stepv.size else np.inf
        speed[~np.isfinite(speed)]=np.inf
        mask=speed<=0.03
        if mask.all() or not mask.any(): mask=np.ones(len(sub),bool)
        op_s=op[mask]; orot_s=orot[mask]; tm_s=tm[mask]
        mdt=float(np.median(np.diff(tm_s)*0.001))
        resid=highpass(op_s,mdt,1.0)
        jt=rms(np.linalg.norm(resid,axis=1))
        rj=rms([relq(orot_s[0],q) for q in orot_s])
        # accuracy on full window (no static mask), translation error
        te=np.linalg.norm(op-gt,axis=1)
        print(f"  [{s}-{e}] {lab:14s} n={len(sub)} jit_t={jt*1000:.2f}mm jit_r={rj:.2f}deg "
              f"trans p50={np.median(te)*1000:.1f} p95={np.percentile(te,95)*1000:.1f}")

for w in [(46,72),(48,72),(50,75)]:
    compute(w)

print("--- validate full segment (0,72) vs report CSV Full 0.31mm/1.99deg NSL 1.30mm/3.57deg ---")
compute((0,72))
