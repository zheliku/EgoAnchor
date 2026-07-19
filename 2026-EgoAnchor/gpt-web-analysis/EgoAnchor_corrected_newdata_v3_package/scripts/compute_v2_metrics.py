from __future__ import annotations
import csv, json, math, sys, zipfile
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation, Slerp

ROOT = Path('/mnt/data')
BASE = ROOT / 'EgoAnchor_corrected_newdata'
DATA = BASE / 'data'
Path('/tmp/xlsx_stream.py').write_bytes(zipfile.ZipFile(ROOT/'EgoAnchor_IEEEVR2027_final_v2_package.zip').read('scripts/xlsx_stream.py'))
sys.path.insert(0,'/tmp')
from xlsx_stream import iter_rows

METHODS=['Arrival-Hold','Capture-Hold','One-Euro Anchor','EgoAnchor']

# Rotation lag/residual
cols=['variant_id','event_id','render_mono_ms','has_display_pose','reference_pose_valid',
      'display_rot_x','display_rot_y','display_rot_z','display_rot_w',
      'reference_rot_x','reference_rot_y','reference_rot_z','reference_rot_w']
raw=defaultdict(list)
for row in iter_rows(ROOT/'task_4_complete(1).xlsx','unity_render',cols):
    v,e=row.get('variant_id'),row.get('event_id')
    if not v or not e or e=='@empty-text' or not row.get('has_display_pose') or not row.get('reference_pose_valid'):
        continue
    try:
        raw[(v,e)].append((float(row['render_mono_ms']), *[float(row[k]) for k in cols[5:]]))
    except Exception:
        continue

def angular_metric(rows):
    a=np.asarray(sorted(rows),float)
    t=a[:,0]; qd=a[:,1:5]; qr=a[:,5:9]
    qd=qd/np.linalg.norm(qd,axis=1,keepdims=True)
    qr=qr/np.linalg.norm(qr,axis=1,keepdims=True)
    t,idx=np.unique(t,return_index=True);qd=qd[idx];qr=qr[idx]
    rd=Rotation.from_quat(qd); rr=Rotation.from_quat(qr); slerp=Slerp(t,rr)
    best=(math.inf, math.nan)
    for lag in np.arange(0,605,5):
        tt=t-lag; valid=(tt>=t[0])&(tt<=t[-1])
        if valid.sum()<30: continue
        rel=rd[valid].inv()*slerp(tt[valid])
        angles=np.degrees(rel.magnitude())
        rmse=float(np.sqrt(np.mean(angles**2)))
        if rmse<best[0]:best=(rmse,float(lag))
    return best[1],best[0]

rot_rows=[]; rot_summary={}
for m in METHODS:
    vals=[]
    for e in sorted(k[1] for k in raw if k[0]==m):
        lag,res=angular_metric(raw[(m,e)]); vals.append((e,lag,res)); rot_rows.append([m,e,lag,res])
    l=np.array([x[1] for x in vals]);r=np.array([x[2] for x in vals])
    rot_summary[m]={
        'lag_median_ms':float(np.median(l)), 'lag_q1_ms':float(np.quantile(l,.25)), 'lag_q3_ms':float(np.quantile(l,.75)),
        'residual_median_deg':float(np.median(r)), 'residual_q1_deg':float(np.quantile(r,.25)), 'residual_q3_deg':float(np.quantile(r,.75)),
        'n_segments':len(vals)}
with (DATA/'task4_rotation_metrics_v2.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.writer(f);w.writerow(['method','segment_id','effective_angular_lag_ms','lag_aligned_angular_rmse_deg']);w.writerows(rot_rows)
(DATA/'task4_rotation_summary_v2.json').write_text(json.dumps(rot_summary,indent=2),encoding='utf-8')

# Transition metric, explicit contract: first sustained 5 mm departure from 250 ms baseline, 100 ms persistence.
cols=['variant_id','event_id','render_mono_ms','has_display_pose','reference_pose_valid',
      'display_pos_x_m','display_pos_y_m','display_pos_z_m',
      'reference_pos_x_m','reference_pos_y_m','reference_pos_z_m']
raw2=defaultdict(list)
for row in iter_rows(ROOT/'task_2_complete(1).xlsx','unity_render',cols):
    v,e=row.get('variant_id'),row.get('event_id')
    if not v or not e or e=='@empty-text' or not row.get('has_display_pose') or not row.get('reference_pose_valid'):
        continue
    try:raw2[(v,e)].append((float(row['render_mono_ms']), *[float(row[k]) for k in cols[5:]]))
    except Exception:continue

def first_sustained(t,x,thr=5.0,persist_ms=100.0):
    mask=x>=thr
    for i in np.where(mask)[0]:
        j=np.searchsorted(t,t[i]+persist_ms,side='left')
        if j>=len(t):break
        if mask[i:j+1].all():return int(i)
    return None

def transition_metric(rows):
    a=np.asarray(sorted(rows),float);t=a[:,0];d=a[:,1:4];r=a[:,4:7];rel=t-t[0]
    base=rel<=250.0
    bd=np.median(d[base],axis=0);br=np.median(r[base],axis=0)
    dd=np.linalg.norm(d-bd,axis=1)*1000;rd=np.linalg.norm(r-br,axis=1)*1000
    ri=first_sustained(t,rd);di=first_sustained(t,dd)
    if ri is None or di is None:return math.nan
    return max(0.0,float(t[di]-t[ri]))
trans_rows=[]; transition_summary={}
for m in METHODS:
    vals=[]
    for e in sorted(k[1] for k in raw2 if k[0]==m):
        val=transition_metric(raw2[(m,e)]);vals.append(val);trans_rows.append([m,e,val])
    a=np.array(vals,float)
    transition_summary[m]={'median_ms':float(np.nanmedian(a)),'q1_ms':float(np.nanquantile(a,.25)),'q3_ms':float(np.nanquantile(a,.75)),'n_segments':int(np.isfinite(a).sum())}
with (DATA/'task2_transition_metrics_v2.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.writer(f);w.writerow(['method','segment_id','start_transition_response_ms']);w.writerows(trans_rows)
(DATA/'task2_transition_summary_v2.json').write_text(json.dumps(transition_summary,indent=2),encoding='utf-8')

# Runtime performance audit from all five new workbooks.
track=[];register=[];all_total=[];pub_intervals=[]
for i in range(1,6):
    pubs=[]
    for row in iter_rows(ROOT/f'task_{i}_complete(1).xlsx','python_candidates'):
        total=row.get('total_ms')
        if isinstance(total,(int,float)):
            total=float(total);all_total.append(total)
            if row.get('phase')=='TRACK':track.append(total)
            elif row.get('phase')=='REGISTER':register.append(total)
        if row.get('has_pose') and isinstance(row.get('server_publish_mono_ms'),(int,float)):
            pubs.append(float(row['server_publish_mono_ms']))
    pubs=np.asarray(sorted(pubs),float)
    if len(pubs)>1:pub_intervals.extend(np.diff(pubs))
perf={
    'all_candidate_total_ms_median':float(np.median(all_total)),
    'all_candidate_total_ms_p95':float(np.percentile(all_total,95)),
    'track_total_ms_median':float(np.median(track)),
    'track_total_ms_p95':float(np.percentile(track,95)),
    'track_n':len(track),
    'register_total_ms_median':float(np.median(register)),
    'register_total_ms_p95':float(np.percentile(register,95)),
    'register_n':len(register),
    'pose_publish_interval_ms_median':float(np.median(pub_intervals)),
    'pose_publish_interval_ms_p95':float(np.percentile(pub_intervals,95)),
    'pose_publish_rate_hz_from_median':float(1000/np.median(pub_intervals)),
    'pose_publish_interval_n':len(pub_intervals),
}
(DATA/'runtime_performance_audit_v2.json').write_text(json.dumps(perf,indent=2),encoding='utf-8')

# Expanded table summary
import pandas as pd
# use standard library instead of pandas output? pandas installed; only CSV creation not spreadsheet editing. okay.
task1=list(csv.DictReader((DATA/'task1_corrected_segment_metrics.csv').open()))
task5=list(csv.DictReader((DATA/'task5_episode_metrics.csv').open()))
task3=json.loads((DATA/'task3_translation_metrics.json').read_text())
rows=[]
for m in METHODS:
    r1=[r for r in task1 if r['variant']==m]
    leak=np.median([float(r['centered_p95_mm']) for r in r1])
    absreg=np.median([float(r['absolute_p95_mm']) for r in r1])
    jitter=np.median([float(r['frame_increment_p95_mm']) for r in r1])
    r5=[r for r in task5 if r['variant']==m]
    occ=np.median([float(r['translation_p95_mm']) for r in r5])
    fail=sum(r['catastrophic_gt40']=='True' for r in r5)
    n=len(r5)
    # task3 json stores summary keys
    t3=task3[m]
    rows.append({
        'method':m,'head_motion_leakage_p95_mm':leak,'absolute_registration_p95_mm':absreg,
        'stationary_frame_increment_p95_mm':jitter,
        'translation_lag_ms':t3['lag_median_ms'],'translation_aligned_rmse_mm':t3['residual_median_mm'],
        'rotation_lag_ms':rot_summary[m]['lag_median_ms'],'rotation_aligned_rmse_deg':rot_summary[m]['residual_median_deg'],
        'occlusion_p95_mm':occ,'catastrophic_failures_gt40':fail,'occlusion_episodes':n,
        'start_transition_response_ms':transition_summary[m]['median_ms']})
with (DATA/'experiment1_expanded_summary_v2.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
print(json.dumps({'rotation':rot_summary,'transition':transition_summary,'performance':perf},indent=2))
