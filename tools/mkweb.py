import re, sys
src = open(sys.argv[1]).read()
out = sys.argv[2]

def rep(old, new, count=1):
    global src
    assert src.count(old) >= 1, ("missing", old[:80])
    src = src.replace(old, new, count)

# ---- document head ----
i = src.index("</style>") + len("</style>")
head = '''<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#16343a">
<meta name="description" content="จัดการลูกค้า โปรเจกต์ ตารางงาน และการเงิน สำหรับเพจท่องเที่ยว">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icons/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="icons/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="โต๊ะงาน">
'''
body = src[i:]
src = head + src[:i] + '''
<style>
html,body{margin:0}
.auth-wrap{min-height:100dvh;display:grid;place-items:center;padding:24px 16px;background:var(--ink)}
.auth{width:100%;max-width:400px;background:var(--surface);border-radius:16px;padding:28px 24px;display:flex;flex-direction:column;gap:14px;box-shadow:0 20px 50px rgba(0,0,0,.25)}
.auth h1{margin:0;font-size:1.35rem}.auth p{margin:0;color:var(--muted);font-size:.9rem}
.auth form{display:flex;flex-direction:column;gap:12px}.auth label{display:flex;flex-direction:column;gap:4px;font-size:.86rem;font-weight:500}
.auth input{font:inherit;padding:10px 12px;border:1px solid var(--line-strong);border-radius:10px;background:var(--surface);color:var(--fg)}
.auth .btn{justify-content:center;padding:11px}.auth .links{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;font-size:.86rem}
.auth .links button{border:0;background:none;color:var(--link);padding:0;font:inherit;cursor:pointer}
.auth .msg{font-size:.86rem;padding:10px 12px;border-radius:10px;background:var(--surface-2)}.auth .msg.err{background:var(--bad-bg);color:var(--bad)}
.members{display:flex;flex-direction:column;gap:6px}.members .li{padding:6px 0}
</style>
</head>
<body>''' + body + '''
</body>
</html>
'''

# ---- scripts: config + supabase before the app script ----
rep('<script>\n(() => {', '<script src="config.js"></script>\n<script src="vendor/supabase.js"></script>\n<script>\n(() => {')

# ---- store ----
s0 = src.index("const store = {"); s1 = src.index("/* ================= finance helpers")
store = r'''const CFG = window.APP_CONFIG || {};
const cloudReady = !!(CFG.supabaseUrl && CFG.supabaseAnonKey && window.supabase);
const errMsg = e => { const m = String(e?.message || e || ""); if (/fetch|network/i.test(m)) return "เชื่อมต่ออินเทอร์เน็ตไม่ได้ ลองอีกครั้ง"; if (/row-level security|permission/i.test(m)) return "บัญชีนี้ไม่มีสิทธิ์แก้ไขข้อมูลนี้"; return "บันทึกไม่สำเร็จ ลองอีกครั้ง"; };
const store = {
  sb:null, ws:null, user:null, chan:null, dl:null,
  async init() {
    if (!cloudReady) { this.initLocal(); return; }
    this.sb = window.supabase.createClient(CFG.supabaseUrl, CFG.supabaseAnonKey, {auth:{persistSession:true, autoRefreshToken:true, detectSessionInUrl:true}});
    this.sb.auth.onAuthStateChange((ev, session) => {
      if (ev === "PASSWORD_RECOVERY") { S.mode = "auth"; S.auth = {view:"newpass"}; render(); return; }
      if (ev === "SIGNED_OUT") { this.reset(); S.mode = "auth"; S.auth = {view:"login"}; render(); return; }
      if (session?.user && (!this.user || this.user.id !== session.user.id) && S.auth?.view !== "newpass") setTimeout(() => this.start(session.user), 0);
    });
    const { data } = await this.sb.auth.getSession();
    if (data?.session?.user) { if (!this.user) this.start(data.session.user); }
    else if (S.auth?.view !== "newpass") { S.mode = "auth"; S.auth ||= {view:"login"}; render(); }
  },
  initLocal() {
    S.mode = "local";
    try { const saved = JSON.parse(localStorage.getItem("cbp-data") || "null"); if (saved) for (const k of COLS) if (Array.isArray(saved[k])) D[k] = saved[k]; } catch {}
    COLS.forEach(c => S.loaded.add(c)); render();
  },
  reset() { if (this.chan) { this.sb.removeChannel(this.chan); this.chan = null; } this.user = null; this.ws = null; S.me = null; S.loaded = new Set(); COLS.forEach(c => D[c] = []); },
  async start(user) {
    this.user = user; S.me = {name:user.email, email:user.email}; S.mode = "cloud"; S.error = null; S.loaded = new Set(); render();
    try {
      const { data:ws, error } = await this.sb.rpc("my_workspace"); if (error) throw error; this.ws = ws;
      const rows = []; for (let from = 0; ; from += 1000) {
        const { data, error:e2 } = await this.sb.from("app_docs").select("col,id,data").eq("workspace_id", ws).neq("col","activity").range(from, from + 999);
        if (e2) throw e2; rows.push(...data); if (data.length < 1000) break; }
      const { data:act, error:e3 } = await this.sb.from("app_docs").select("col,id,data").eq("workspace_id", ws).eq("col","activity").order("updated_at", {ascending:false}).limit(80);
      if (e3) throw e3;
      COLS.forEach(c => D[c] = []);
      for (const r of rows.concat(act)) if (D[r.col]) D[r.col].push({...r.data, id:r.id});
      this.sortActivity();
      this.chan = this.sb.channel("docs-" + ws).on("postgres_changes", {event:"*", schema:"public", table:"app_docs", filter:"workspace_id=eq." + ws}, p => this.apply(p)).subscribe();
      COLS.forEach(c => S.loaded.add(c)); render();
    } catch (e) { S.error = "โหลดข้อมูลไม่สำเร็จ: " + (e?.message || "ไม่ทราบสาเหตุ") + " ลองรีเฟรชหน้า"; COLS.forEach(c => S.loaded.add(c)); render(); }
  },
  sortActivity() { D.activity.sort((a,b) => (b.at||"").localeCompare(a.at||"")); D.activity = D.activity.slice(0,80); },
  put(col, id, body) { const arr = D[col]; if (!arr) return; const i = arr.findIndex(x => x.id === id); const row = {...body, id}; if (i >= 0) arr[i] = row; else arr.push(row); if (col === "activity") this.sortActivity(); },
  drop(col, id) { if (D[col]) D[col] = D[col].filter(x => x.id !== id); },
  apply(p) {
    if (p.eventType === "DELETE") { const o = p.old || {}; if (o.col && o.id) this.drop(o.col, o.id); }
    else { const n = p.new || {}; if (n.col && n.id) this.put(n.col, n.id, n.data || {}); }
    clearTimeout(this._rt); this._rt = setTimeout(render, 60);
  },
  persist() { try { localStorage.setItem("cbp-data", JSON.stringify(D)); } catch {} },
  async save(col, id, data, logText) {
    id = id || newId();
    const body = {...data, updatedAt:new Date().toISOString()};
    delete body.id;
    if (!body.createdAt) body.createdAt = body.updatedAt;
    if (this.sb) {
      const { error } = await this.sb.from("app_docs").upsert({workspace_id:this.ws, col, id, data:body, updated_at:body.updatedAt});
      if (error) { toast(errMsg(error), true); throw error; }
      this.put(col, id, body); render();
    } else { this.put(col, id, body); this.persist(); render(); }
    if (logText) this.log(logText, col, id);
    return id;
  },
  async remove(col, id, logText) {
    if (this.sb) {
      const { error } = await this.sb.from("app_docs").delete().match({workspace_id:this.ws, col, id});
      if (error) { toast("ลบไม่สำเร็จ ลองอีกครั้ง", true); throw error; }
    }
    this.drop(col, id); if (!this.sb) this.persist(); render();
    if (logText) this.log(logText, col, id);
  },
  async log(text, col, ref) {
    const id = newId(); const body = {at:new Date().toISOString(), text, col:col||"", ref:ref||""};
    if (this.sb) { const { error } = await this.sb.from("app_docs").upsert({workspace_id:this.ws, col:"activity", id, data:body}); if (error) return; }
    this.put("activity", id, body); if (!this.sb) this.persist(); render();
  },
  async importAll(data) {
    const rows = []; for (const c of COLS) for (const x of (Array.isArray(data[c]) ? data[c] : [])) { if (!x || typeof x !== "object" || !x.id) continue; const {id, ...rest} = x; rows.push({col:c, id:String(id).slice(0,80), data:rest}); }
    if (!rows.length) throw new Error("ไม่พบข้อมูลในไฟล์");
    if (this.sb) { for (let i = 0; i < rows.length; i += 200) { const { error } = await this.sb.from("app_docs").upsert(rows.slice(i, i+200).map(r => ({...r, workspace_id:this.ws}))); if (error) throw error; } }
    rows.forEach(r => this.put(r.col, r.id, r.data)); if (!this.sb) this.persist(); render();
    return rows.length;
  },
};

/* ================= sign-in screen ================= */
function vAuth() {
  const a = S.auth || {view:"login"}; const v = a.view;
  const title = {login:"เข้าสู่ระบบ", signup:"สมัครใช้งาน", forgot:"ลืมรหัสผ่าน", newpass:"ตั้งรหัสผ่านใหม่"}[v];
  const fields = v === "newpass" ? `<label>รหัสผ่านใหม่ (อย่างน้อย 8 ตัว)<input id="au-pass" type="password" autocomplete="new-password" minlength="8" required></label>`
    : `<label>อีเมล<input id="au-email" type="email" autocomplete="email" required value="${esc(a.email||"")}"></label>${v === "forgot" ? "" : `<label>รหัสผ่าน${v==="signup"?" (อย่างน้อย 8 ตัว)":""}<input id="au-pass" type="password" autocomplete="${v==="signup"?"new-password":"current-password"}" ${v==="signup"?'minlength="8"':""} required></label>`}`;
  const links = v === "login" ? `<button type="button" data-auth="signup">สมัครใช้งานครั้งแรก</button><button type="button" data-auth="forgot">ลืมรหัสผ่าน</button>`
    : v === "newpass" ? "" : `<button type="button" data-auth="login">กลับไปหน้าเข้าสู่ระบบ</button>`;
  return `<div class="auth-wrap"><main class="auth"><div><h1>โต๊ะงานสายเที่ยว</h1><p>${title}</p></div>
    ${a.msg ? `<div class="msg ${a.err?"err":""}" role="status">${esc(a.msg)}</div>` : ""}
    <form id="authForm">${fields}<button class="btn primary" type="submit" ${a.busy?"disabled":""}>${a.busy ? "กำลังดำเนินการ…" : {login:"เข้าสู่ระบบ", signup:"สมัครใช้งาน", forgot:"ส่งลิงก์ตั้งรหัสผ่านใหม่", newpass:"บันทึกรหัสผ่าน"}[v]}</button></form>
    <div class="links">${links}</div></main></div>`;
}
const authErr = e => { const m = String(e?.message || ""); if (/invalid login/i.test(m)) return "อีเมลหรือรหัสผ่านไม่ถูกต้อง"; if (/not confirmed/i.test(m)) return "ยังไม่ได้ยืนยันอีเมล เปิดลิงก์ในอีเมลที่ได้รับก่อน"; if (/already registered/i.test(m)) return "อีเมลนี้สมัครไว้แล้ว ลองเข้าสู่ระบบ"; if (/password/i.test(m)) return "รหัสผ่านสั้นหรือง่ายเกินไป"; if (/rate|seconds/i.test(m)) return "ส่งคำขอถี่เกินไป รอสักครู่แล้วลองใหม่"; if (/fetch|network/i.test(m)) return "เชื่อมต่ออินเทอร์เน็ตไม่ได้"; return "ทำรายการไม่สำเร็จ: " + m; };
async function submitAuth(f) {
  const a = S.auth; const sb = store.sb; const email = $("#au-email", f)?.value.trim(); const pass = $("#au-pass", f)?.value;
  S.auth = {...a, email, busy:true, msg:"", err:false}; render();
  const redirectTo = location.origin + location.pathname;
  try {
    if (a.view === "login") { const { error } = await sb.auth.signInWithPassword({email, password:pass}); if (error) throw error; S.auth = {view:"login"}; return; }
    if (a.view === "signup") { const { data, error } = await sb.auth.signUp({email, password:pass, options:{emailRedirectTo:redirectTo}}); if (error) throw error;
      S.auth = data.session ? {view:"login"} : {view:"login", email, msg:"สมัครแล้ว เปิดลิงก์ยืนยันในอีเมล แล้วกลับมาเข้าสู่ระบบ"}; }
    if (a.view === "forgot") { const { error } = await sb.auth.resetPasswordForEmail(email, {redirectTo}); if (error) throw error; S.auth = {view:"login", email, msg:"ส่งลิงก์ไปที่อีเมลแล้ว เปิดลิงก์เพื่อตั้งรหัสผ่านใหม่"}; }
    if (a.view === "newpass") { const { data, error } = await sb.auth.updateUser({password:pass}); if (error) throw error; S.auth = {view:"login"}; toast("ตั้งรหัสผ่านใหม่แล้ว"); store.start(data.user); return; }
  } catch (e) { S.auth = {...S.auth, busy:false, msg:authErr(e), err:true}; }
  render();
}

'''
src = src[:s0] + store + src[s1:]

# ---- render: auth screen ----
rep('function render() {\n', '''function render() {
  if (S.mode === "auth") { root.innerHTML = vAuth(); const f = $("#authForm"); if (f) { f.onsubmit = e => { e.preventDefault(); submitAuth(f); }; $("input", f)?.focus(); } $$("[data-auth]").forEach(b => b.onclick = () => { S.auth = {view:b.dataset.auth, email:$("#au-email")?.value||""}; render(); }); return; }
''')
rep('''if (S.mode === "local") inner += `<p class="muted" style="font-size:.78rem;margin:0">โหมดทดลอง: เปิดนอก Claude จึงเก็บข้อมูลไว้ในเบราว์เซอร์นี้เท่านั้น</p>`;''',
    '''if (S.mode === "local") inner = `<div class="banner">ยังไม่ได้เชื่อมฐานข้อมูล ข้อมูลเก็บไว้ในเบราว์เซอร์นี้เท่านั้น (ใส่ค่าใน config.js เพื่อใช้งานจริง)</div>` + inner;''')
rep('"โหมดทดลอง" : "บัญชีของคุณ"', '"ยังไม่เชื่อมฐานข้อมูล" : "บัญชีของคุณ"')

# ---- settings: account block ----
old_acc = re.search(r'      <div>\$\{S\.mode==="db" \?.*?</div>\n', src).group(0)
src = src.replace(old_acc, '      ${accountBlock()}\n', 1)
rep('<span class="muted" style="font-size:.78rem">ไฟล์สำรองใช้ย้ายข้อมูลไปฐานข้อมูลอื่น เช่น Supabase ได้ภายหลัง</span></div></section>',
    '''<label class="btn" style="align-self:flex-start">${ico("plus")}นำเข้าจากไฟล์สำรอง (JSON)<input type="file" id="importFile" accept="application/json,.json" hidden></label>
      <span class="muted" style="font-size:.78rem">ใช้ย้ายข้อมูลจากแอปเวอร์ชันใน Claude: กด “สำรองข้อมูลทั้งหมด” ที่แอปเดิม แล้วนำไฟล์มานำเข้าที่นี่ รายการที่ซ้ำกันจะถูกเขียนทับ ไม่เกิดรายการซ้ำ</span></div></section>
    ${S.mode === "cloud" ? `<section class="card"><div class="card-h"><h2>ทีมงาน</h2></div><div class="card-b" style="display:flex;flex-direction:column;gap:10px" id="teamBox"><span class="muted">กำลังโหลด…</span></div></section>` : ""}''')
rep("/* ================= render ================= */", r'''function accountBlock() {
  if (S.mode === "cloud") return `<div>เข้าสู่ระบบด้วย <b>${esc(S.me?.email || "")}</b> ข้อมูลเห็นได้เฉพาะคนในทีมของคุณ</div><div><button class="btn" data-act="signOut">ออกจากระบบ</button></div>`;
  return `<div>ยังไม่ได้เชื่อมฐานข้อมูล ข้อมูลเก็บในเบราว์เซอร์นี้เท่านั้น</div>`;
}
async function loadTeam() {
  const box = $("#teamBox"); if (!box || !store.sb) return;
  const { data, error } = await store.sb.rpc("list_members", {ws:store.ws});
  if (!$("#teamBox")) return;
  if (error) { box.innerHTML = `<span class="neg">โหลดรายชื่อทีมไม่สำเร็จ</span>`; return; }
  const meOwner = data.some(m => m.user_id === store.user.id && m.role === "owner");
  box.innerHTML = `<div class="members">${data.map(m => `<div class="li"><span class="m"><span class="t">${esc(m.email)}</span><span class="s">${m.role === "owner" ? "เจ้าของ" : "สมาชิก แก้ไขได้ทุกอย่าง"}</span></span>${meOwner && m.role !== "owner" ? `<span class="r"><button class="btn sm" data-act="removeMember" data-id="${m.user_id}" data-email="${esc(m.email)}">นำออก</button></span>` : ""}</div>`).join("")}</div>
    ${meOwner ? `<form id="addMember" style="display:flex;gap:8px;flex-wrap:wrap"><input id="am-email" type="email" required placeholder="อีเมลของคนในทีม" style="flex:1;min-width:180px;font:inherit;padding:8px 10px;border:1px solid var(--line-strong);border-radius:10px;background:var(--surface);color:var(--fg)"><button class="btn" type="submit">${ico("plus")}เพิ่มเข้าทีม</button></form>
    <span class="muted" style="font-size:.78rem">ให้คนในทีมกด “สมัครใช้งาน” ด้วยอีเมลของเขาก่อน แล้วค่อยเพิ่มที่นี่</span>` : ""}`;
  const f = $("#addMember"); if (f) f.onsubmit = async e => { e.preventDefault(); const em = $("#am-email").value.trim();
    const { data:r, error:er } = await store.sb.rpc("add_member", {ws:store.ws, member_email:em});
    if (er) toast("เพิ่มไม่สำเร็จ", true); else if (r === "not_found") toast("ยังไม่มีบัญชีนี้ ให้เขาสมัครใช้งานก่อน", true); else { toast("เพิ่ม " + em + " เข้าทีมแล้ว"); loadTeam(); } };
}

/* ================= render ================= */''')
rep("  root.innerHTML = shell(inner);\n", "  root.innerHTML = shell(inner);\n  if ($(\"#teamBox\")) loadTeam();\n")

# ---- actions ----
rep("const ACT = {\n", '''const ACT = {
  signOut() { confirmBox("ออกจากระบบบนเครื่องนี้?", async () => { closeModal(); await store.sb.auth.signOut(); }); },
  removeMember(el) { confirmBox(`นำ <b>${esc(el.dataset.email)}</b> ออกจากทีม?`, async () => { const { error } = await store.sb.rpc("remove_member", {ws:store.ws, member:el.dataset.id}); closeModal(); if (error) toast("นำออกไม่สำเร็จ", true); else { toast("นำออกแล้ว"); loadTeam(); } }); },
''')

# ---- downloads: plain browser download ----
s0 = src.index("async function saveFile(filename, data) {"); s1 = src.index("const csvCell")
src = src[:s0] + '''async function saveFile(filename, data) {
  try {
    const type = /\\.csv$/.test(filename) ? "text/csv;charset=utf-8" : /\\.json$/.test(filename) ? "application/json" : "text/html;charset=utf-8";
    const url = URL.createObjectURL(new Blob([data], {type})); const a = document.createElement("a");
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
    toast("ดาวน์โหลด " + filename);
  } catch { toast("ดาวน์โหลดไม่สำเร็จ", true); }
}
''' + src[s1:]

# ---- import listener + service worker ----
rep("/* ================= boot ================= */", '''document.addEventListener("change", async e => {
  if (e.target.id !== "importFile") return; const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
  let parsed; try { parsed = JSON.parse(await file.text()); } catch { toast("ไฟล์นี้ไม่ใช่ไฟล์สำรองที่ถูกต้อง", true); return; }
  const data = parsed?.data && typeof parsed.data === "object" ? parsed.data : parsed;
  const n = COLS.reduce((s, c) => s + (Array.isArray(data?.[c]) ? data[c].length : 0), 0);
  if (!n) { toast("ไม่พบข้อมูลในไฟล์", true); return; }
  confirmBox(`นำเข้า <b>${n}</b> รายการจาก ${esc(file.name)}?`, async () => {
    try { const k = await store.importAll(data); closeModal(); toast(`นำเข้าแล้ว ${k} รายการ`); store.log(`นำเข้าข้อมูลจากไฟล์สำรอง ${k} รายการ`); }
    catch (er) { closeModal(); toast("นำเข้าไม่สำเร็จ: " + (er?.message || ""), true); }
  });
});
if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});

/* ================= boot ================= */''')
open(out, "w").write(src)
print("written", len(src))
