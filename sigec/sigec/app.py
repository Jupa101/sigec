"""SIGEC - Sistema de Gestión y Seguimiento de Capacitaciones."""
import os, io, csv, sqlite3
from datetime import date
from functools import wraps
from secrets import token_hex
from flask import (Flask, g, session, request, redirect, url_for, flash,
                   render_template, abort, Response)
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash

DB = os.environ.get("DB_PATH", "sigec.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-en-produccion")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuario(id_usuario INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
 usuario TEXT NOT NULL UNIQUE, contrasena_hash TEXT NOT NULL,
 rol TEXT NOT NULL CHECK(rol IN('admin','facilitador')));
CREATE TABLE IF NOT EXISTS capacitacion(id_capacitacion INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
 tema TEXT, fecha_hora TEXT NOT NULL, modalidad TEXT NOT NULL CHECK(modalidad IN('Presencial','Virtual')),
 lugar_enlace TEXT NOT NULL, cupos_totales INTEGER NOT NULL CHECK(cupos_totales>0),
 estado TEXT NOT NULL DEFAULT 'Programada' CHECK(estado IN('Programada','Realizada','Cancelada')),
 id_usuario INTEGER NOT NULL REFERENCES usuario(id_usuario));
CREATE TABLE IF NOT EXISTS participante(id_participante INTEGER PRIMARY KEY,
 numero_identificacion TEXT NOT NULL UNIQUE, nombres TEXT NOT NULL, apellidos TEXT NOT NULL,
 correo TEXT NOT NULL, telefono TEXT, empresa TEXT);
CREATE TABLE IF NOT EXISTS inscripcion(id_inscripcion INTEGER PRIMARY KEY,
 id_participante INTEGER NOT NULL REFERENCES participante(id_participante),
 id_capacitacion INTEGER NOT NULL REFERENCES capacitacion(id_capacitacion),
 fecha_inscripcion TEXT NOT NULL, UNIQUE(id_participante,id_capacitacion));
CREATE TABLE IF NOT EXISTS asistencia(id_asistencia INTEGER PRIMARY KEY,
 id_inscripcion INTEGER NOT NULL UNIQUE REFERENCES inscripcion(id_inscripcion) ON DELETE CASCADE,
 estado TEXT NOT NULL DEFAULT 'Inscrito' CHECK(estado IN('Inscrito','Asistió','No asistió')), fecha_registro TEXT);
"""
ESTADOS_ASIS = ["Inscrito", "Asistió", "No asistió"]
F_CAP = [("nombre", "Nombre", "text"), ("tema", "Tema", "text"), ("fecha_hora", "Fecha y hora", "datetime-local"),
         ("modalidad", "Modalidad", ["Presencial", "Virtual"]), ("lugar_enlace", "Lugar o enlace", "text"),
         ("cupos_totales", "Cupos totales", "number"), ("estado", "Estado", ["Programada", "Realizada", "Cancelada"])]
F_PAR = [("numero_identificacion", "Identificación", "text"), ("nombres", "Nombres", "text"),
         ("apellidos", "Apellidos", "text"), ("correo", "Correo electrónico", "email"),
         ("telefono", "Teléfono", "text"), ("empresa", "Empresa u organización", "text")]
OBLIG = {"nombre", "fecha_hora", "lugar_enlace", "cupos_totales", "numero_identificacion", "nombres", "apellidos", "correo"}

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db
@app.teardown_appcontext
def close(_):
    c = g.pop("db", None)
    if c: c.close()
def q(sql, *a, one=False):
    r = db().execute(sql, a).fetchall()
    return (r[0] if r else None) if one else r
def run(sql, *a):
    try:
        db().execute(sql, a); db().commit(); return True
    except sqlite3.IntegrityError:
        return False
def init_db():
    c = sqlite3.connect(DB, timeout=30); c.executescript(SCHEMA)
    c.execute("BEGIN IMMEDIATE")  # serializa el arranque cuando hay varios procesos
    if not c.execute("SELECT 1 FROM usuario").fetchone():
        c.execute("INSERT INTO usuario(nombre,usuario,contrasena_hash,rol) VALUES(?,?,?,'admin')",
                  ("Administrador RR.HH.", os.environ.get("ADMIN_USER", "admin"),
                   generate_password_hash(os.environ.get("ADMIN_PASS", "admin123"))))
    if os.environ.get("SEED_DEMO") and not c.execute("SELECT 1 FROM capacitacion").fetchone():
        for r in [("Seguridad y salud en el trabajo", "SST", "2026-11-10T09:00", "Presencial", "Sala 2", 3),
                  ("Excel intermedio", "Ofimática", "2026-11-17T14:00", "Virtual", "meet.google.com/demo", 20),
                  ("Servicio al cliente", "Habilidades blandas", "2026-10-01T08:00", "Presencial", "Auditorio", 15)]:
            c.execute("INSERT INTO capacitacion(nombre,tema,fecha_hora,modalidad,lugar_enlace,cupos_totales,estado,id_usuario)"
                      " VALUES(?,?,?,?,?,?,?,1)", r + (("Realizada",) if "Servicio" in r[0] else ("Programada",)))
        for i, (n, ap) in enumerate([("Ana", "Gómez"), ("Luis", "Pérez"), ("Marta", "Rojas"), ("Carlos", "Díaz")], 1):
            c.execute("INSERT INTO participante(numero_identificacion,nombres,apellidos,correo,telefono,empresa) VALUES(?,?,?,?,?,?)",
                      (str(1000 + i), n, ap, f"{n.lower()}@empresa.co", "3000000000", "Empresa Demo"))
        for cap, pars in [(1, (1, 2, 3)), (3, (1, 2, 4))]:
            for p in pars:
                cur = c.execute("INSERT INTO inscripcion(id_participante,id_capacitacion,fecha_inscripcion) VALUES(?,?,?)",
                                (p, cap, "2026-10-01"))
                c.execute("INSERT INTO asistencia(id_inscripcion,estado) VALUES(?,?)", (cur.lastrowid, "Asistió" if cap == 3 else "Inscrito"))
    c.commit(); c.close()

app.jinja_env.globals["csrf"] = lambda: session.setdefault("_t", token_hex(16))
@app.before_request
def csrf_check():
    if request.method == "POST" and request.form.get("_t") != session.get("_t"):
        abort(400)

def need(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session: return redirect(url_for("login"))
            if roles and session["rol"] not in roles: abort(403)
            return f(*a, **k)
        return w
    return deco

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("SELECT * FROM usuario WHERE usuario=?", request.form["usuario"].strip(), one=True)
        if u and check_password_hash(u["contrasena_hash"], request.form["clave"]):
            session.clear(); session.update(uid=u["id_usuario"], rol=u["rol"], nombre=u["nombre"])
            return redirect(url_for("inicio"))
        flash("Usuario o contraseña incorrectos.", "err")
    return render_template("login.html")
@app.post("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
@need()
def inicio():
    n = {t: q(f"SELECT COUNT(*) c FROM {t}", one=True)["c"] for t in ("capacitacion", "participante", "inscripcion")}
    prox = q("SELECT * FROM capacitacion WHERE estado='Programada' ORDER BY fecha_hora LIMIT 5")
    return render_template("inicio.html", n=n, prox=prox)

@app.route("/usuarios", methods=["GET", "POST"])
@need("admin")
def usuarios():
    if request.method == "POST":
        f = request.form
        if len(f["clave"]) < 8 or not f["nombre"].strip() or not f["usuario"].strip():
            flash("Completa todos los campos; la contraseña debe tener mínimo 8 caracteres.", "err")
        elif run("INSERT INTO usuario(nombre,usuario,contrasena_hash,rol) VALUES(?,?,?,?)", f["nombre"].strip(),
                 f["usuario"].strip(), generate_password_hash(f["clave"]), f["rol"]):
            flash("Usuario creado.", "ok")
        else: flash("Ese nombre de usuario ya existe.", "err")
        return redirect(url_for("usuarios"))
    return render_template("usuarios.html", us=q("SELECT * FROM usuario ORDER BY nombre"))

def read_form(fields):
    d = {k: request.form.get(k, "").strip() for k, _, _ in fields}
    if any(not d[k] for k in d if k in OBLIG):
        return None, "Completa los campos obligatorios."
    if "cupos_totales" in d:
        if not d["cupos_totales"].isdigit() or int(d["cupos_totales"]) < 1:
            return None, "Los cupos deben ser un número mayor que cero."
    return d, None

@app.route("/capacitaciones")
@need()
def capacitaciones():
    rows = q("""SELECT c.*, (SELECT COUNT(*) FROM inscripcion i WHERE i.id_capacitacion=c.id_capacitacion) ins
                FROM capacitacion c ORDER BY fecha_hora DESC""")
    return render_template("caps.html", rows=rows)

@app.route("/capacitaciones/nueva", methods=["GET", "POST"])
@app.route("/capacitaciones/<int:cid>/editar", methods=["GET", "POST"])
@need("admin")
def cap_form(cid=None):
    cur = q("SELECT * FROM capacitacion WHERE id_capacitacion=?", cid, one=True) if cid else None
    if cid and not cur: abort(404)
    if request.method == "POST":
        d, err = read_form(F_CAP)
        if not err and cid:
            ins = q("SELECT COUNT(*) c FROM inscripcion WHERE id_capacitacion=?", cid, one=True)["c"]
            if int(d["cupos_totales"]) < ins: err = f"Ya hay {ins} inscritos; los cupos no pueden ser menos."
        if err: flash(err, "err")
        else:
            v = [d[k] for k, _, _ in F_CAP]
            if cid: run("""UPDATE capacitacion SET nombre=?,tema=?,fecha_hora=?,modalidad=?,lugar_enlace=?,
                        cupos_totales=?,estado=? WHERE id_capacitacion=?""", *v, cid)
            else: run("""INSERT INTO capacitacion(nombre,tema,fecha_hora,modalidad,lugar_enlace,cupos_totales,estado,
                      id_usuario) VALUES(?,?,?,?,?,?,?,?)""", *v, session["uid"])
            flash("Capacitación guardada.", "ok"); return redirect(url_for("capacitaciones"))
    return render_template("form.html", titulo="Editar capacitación" if cid else "Nueva capacitación",
                           fields=F_CAP, v=cur or request.form or {"estado": "Programada"}, back="capacitaciones")

@app.route("/capacitaciones/<int:cid>")
@need()
def cap_detalle(cid):
    c = q("SELECT * FROM capacitacion WHERE id_capacitacion=?", cid, one=True) or abort(404)
    ins = q("""SELECT i.id_inscripcion, p.nombres||' '||p.apellidos AS nom, p.numero_identificacion ident, a.estado
               FROM inscripcion i JOIN participante p USING(id_participante)
               JOIN asistencia a USING(id_inscripcion) WHERE i.id_capacitacion=? ORDER BY p.apellidos""", cid)
    libres = q("""SELECT * FROM participante WHERE id_participante NOT IN
               (SELECT id_participante FROM inscripcion WHERE id_capacitacion=?) ORDER BY apellidos""", cid)
    return render_template("cap.html", c=c, ins=ins, libres=libres, est=ESTADOS_ASIS,
                           disp=c["cupos_totales"] - len(ins))

@app.post("/capacitaciones/<int:cid>/inscribir")
@need("admin")
def inscribir(cid):
    c = q("SELECT * FROM capacitacion WHERE id_capacitacion=?", cid, one=True) or abort(404)
    n = q("SELECT COUNT(*) c FROM inscripcion WHERE id_capacitacion=?", cid, one=True)["c"]
    if c["estado"] != "Programada": flash("Solo se inscribe en capacitaciones programadas.", "err")
    elif n >= c["cupos_totales"]: flash("No hay cupos disponibles.", "err")
    elif not request.form.get("pid"): flash("Elige un participante.", "err")
    else:
        db().execute("INSERT OR IGNORE INTO inscripcion(id_participante,id_capacitacion,fecha_inscripcion) VALUES(?,?,?)",
                     (request.form["pid"], cid, date.today().isoformat()))
        db().execute("INSERT OR IGNORE INTO asistencia(id_inscripcion) SELECT id_inscripcion FROM inscripcion "
                     "WHERE id_participante=? AND id_capacitacion=?", (request.form["pid"], cid))
        db().commit(); flash("Participante inscrito.", "ok")
    return redirect(url_for("cap_detalle", cid=cid))

@app.post("/inscripciones/<int:iid>/cancelar")
@need("admin")
def cancelar(iid):
    r = q("SELECT id_capacitacion FROM inscripcion WHERE id_inscripcion=?", iid, one=True) or abort(404)
    run("DELETE FROM inscripcion WHERE id_inscripcion=?", iid); flash("Inscripción cancelada; el cupo quedó libre.", "ok")
    return redirect(url_for("cap_detalle", cid=r["id_capacitacion"]))

@app.post("/capacitaciones/<int:cid>/asistencia")
@need("admin", "facilitador")
def asistencia(cid):
    for k, v in request.form.items():
        if k.startswith("a_") and v in ESTADOS_ASIS:
            db().execute("""UPDATE asistencia SET estado=?, fecha_registro=? WHERE id_inscripcion=? AND id_inscripcion IN
                         (SELECT id_inscripcion FROM inscripcion WHERE id_capacitacion=?)""",
                         (v, date.today().isoformat(), k[2:], cid))
    db().commit(); flash("Asistencia guardada.", "ok")
    return redirect(url_for("cap_detalle", cid=cid))

@app.route("/participantes")
@need()
def participantes():
    s = f"%{request.args.get('q', '').strip()}%"
    return render_template("pars.html", rows=q("""SELECT * FROM participante WHERE nombres||' '||apellidos LIKE ?
                           OR numero_identificacion LIKE ? OR empresa LIKE ? ORDER BY apellidos""", s, s, s))

@app.route("/participantes/nuevo", methods=["GET", "POST"])
@app.route("/participantes/<int:pid>/editar", methods=["GET", "POST"])
@need("admin")
def par_form(pid=None):
    cur = q("SELECT * FROM participante WHERE id_participante=?", pid, one=True) if pid else None
    if pid and not cur: abort(404)
    if request.method == "POST":
        d, err = read_form(F_PAR)
        if err: flash(err, "err")
        else:
            v = [d[k] for k, _, _ in F_PAR]
            ok = run("""UPDATE participante SET numero_identificacion=?,nombres=?,apellidos=?,correo=?,telefono=?,
                     empresa=? WHERE id_participante=?""", *v, pid) if pid else run(
                "INSERT INTO participante(numero_identificacion,nombres,apellidos,correo,telefono,empresa) VALUES(?,?,?,?,?,?)", *v)
            if ok: flash("Participante guardado.", "ok"); return redirect(url_for("participantes"))
            flash("Ya existe un participante con esa identificación.", "err")
    return render_template("form.html", titulo="Editar participante" if pid else "Nuevo participante",
                           fields=F_PAR, v=cur or request.form or {}, back="participantes")

RESUMEN = """SELECT c.id_capacitacion, c.nombre, c.fecha_hora, c.estado, c.cupos_totales,
 COUNT(i.id_inscripcion) inscritos, COALESCE(SUM(a.estado='Asistió'),0) asistieron,
 COALESCE(SUM(a.estado='No asistió'),0) no_asistieron
 FROM capacitacion c LEFT JOIN inscripcion i USING(id_capacitacion) LEFT JOIN asistencia a USING(id_inscripcion)
 GROUP BY c.id_capacitacion ORDER BY c.fecha_hora DESC"""

@app.route("/reportes")
@need()
def reportes():
    pid = request.args.get("pid")
    hist = q("""SELECT c.nombre, c.fecha_hora, a.estado FROM inscripcion i JOIN capacitacion c USING(id_capacitacion)
             JOIN asistencia a USING(id_inscripcion) WHERE i.id_participante=? ORDER BY c.fecha_hora DESC""", pid) if pid else []
    return render_template("rep.html", res=q(RESUMEN), pars=q("SELECT * FROM participante ORDER BY apellidos"),
                           hist=hist, pid=pid)

@app.route("/reportes.csv")
@need()
def reportes_csv():
    o = io.StringIO(); w = csv.writer(o)
    w.writerow(["Capacitación", "Fecha", "Estado", "Cupos", "Inscritos", "Asistieron", "No asistieron"])
    for r in q(RESUMEN): w.writerow([r["nombre"], r["fecha_hora"], r["estado"], r["cupos_totales"],
                                     r["inscritos"], r["asistieron"], r["no_asistieron"]])
    return Response("\ufeff" + o.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=reporte_capacitaciones.csv"})

T = {}
T["base.html"] = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SIGEC</title><style>
:root{--ink:#1c2a33;--mut:#5d6b75;--line:#d9e0e4;--bg:#f3f6f7;--ac:#0e5a57;--ac2:#e8f2f1;--err:#a6362b;--ok:#2d6a3e}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--ac);color:#fff;display:flex;flex-wrap:wrap;align-items:center;gap:.25rem 1.25rem;padding:.6rem 1.25rem}
header b{font-size:1.2rem;margin-right:.5rem}header a{color:#fff;text-decoration:none;padding:.25rem .1rem;border-bottom:2px solid transparent}
header a:hover,header a:focus-visible{border-color:#fff;outline:none}header form{margin-left:auto;display:flex;gap:.6rem;align-items:center}
main{max-width:62rem;margin:1.5rem auto;padding:0 1rem}h1{font-size:1.6rem;margin:.2rem 0 1rem}
.card{background:#fff;border:1px solid var(--line);border-radius:6px;padding:1rem;margin-bottom:1rem;overflow-x:auto}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line)}th{color:var(--mut);font-weight:600}
label{display:block;margin:.7rem 0 .2rem;font-weight:600}input,select{width:100%;max-width:30rem;padding:.5rem;border:1px solid #aeb9bf;border-radius:4px;font:inherit}
button,.btn{background:var(--ac);color:#fff;border:0;border-radius:4px;padding:.5rem .9rem;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
button.sec,.btn.sec{background:var(--ac2);color:var(--ac)}button.lnk{background:none;color:#fff;padding:0}button.del{background:#fff;color:var(--err);border:1px solid var(--err)}
:focus-visible{outline:3px solid #f0b429;outline-offset:2px}.msg{padding:.6rem .9rem;border-radius:4px;margin-bottom:.8rem}
.ok{background:#e4f3e8;color:var(--ok)}.err{background:#fbe6e3;color:var(--err)}.row{display:flex;gap:1rem;flex-wrap:wrap}
.n{font-size:2rem;font-weight:700;color:var(--ac)}.row .card{flex:1;min-width:10rem;margin:0 0 1rem}.mut{color:var(--mut)}</style></head><body>
<header><b>SIGEC</b>{% if session.uid %}<a href="/">Inicio</a><a href="/capacitaciones">Capacitaciones</a>
<a href="/participantes">Participantes</a><a href="/reportes">Reportes</a>{% if session.rol=='admin' %}<a href="/usuarios">Usuarios</a>{% endif %}
<form method="post" action="/logout"><span>{{session.nombre}}</span><input type="hidden" name="_t" value="{{csrf()}}">
<button class="lnk">Cerrar sesión</button></form>{% endif %}</header><main>
{% for c,m in get_flashed_messages(with_categories=true) %}<div class="msg {{c}}" role="status">{{m}}</div>{% endfor %}
{% block c %}{% endblock %}</main></body></html>"""
HID = '<input type="hidden" name="_t" value="{{csrf()}}">'
T["login.html"] = """{% extends 'base.html' %}{% block c %}<div class="card" style="max-width:24rem;margin:3rem auto">
<h1>Ingresar a SIGEC</h1><form method="post">""" + HID + """<label for="u">Usuario</label><input id="u" name="usuario" required autofocus>
<label for="k">Contraseña</label><input id="k" name="clave" type="password" required><p><button>Ingresar</button></p></form></div>{% endblock %}"""
T["inicio.html"] = """{% extends 'base.html' %}{% block c %}<h1>Resumen</h1><div class="row">
<div class="card"><div class="n">{{n.capacitacion}}</div>capacitaciones</div><div class="card"><div class="n">{{n.participante}}</div>participantes</div>
<div class="card"><div class="n">{{n.inscripcion}}</div>inscripciones</div></div><div class="card"><h2>Próximas capacitaciones</h2>
{% for c in prox %}<p><a href="/capacitaciones/{{c.id_capacitacion}}">{{c.nombre}}</a> <span class="mut">{{c.fecha_hora.replace('T',' ')}}</span></p>
{% else %}<p class="mut">No hay capacitaciones programadas. Crea la primera desde Capacitaciones.</p>{% endfor %}</div>{% endblock %}"""
T["usuarios.html"] = """{% extends 'base.html' %}{% block c %}<h1>Usuarios</h1><div class="card"><table><tr><th>Nombre</th><th>Usuario</th><th>Rol</th></tr>
{% for u in us %}<tr><td>{{u.nombre}}</td><td>{{u.usuario}}</td><td>{{u.rol}}</td></tr>{% endfor %}</table></div>
<div class="card"><h2>Crear usuario</h2><form method="post">""" + HID + """<label>Nombre completo</label><input name="nombre" required>
<label>Usuario</label><input name="usuario" required><label>Contraseña (mínimo 8 caracteres)</label><input name="clave" type="password" minlength="8" required>
<label>Rol</label><select name="rol"><option value="admin">admin (gestiona todo)</option><option value="facilitador">facilitador (consulta y toma asistencia)</option></select>
<p><button>Crear usuario</button></p></form></div>{% endblock %}"""
T["form.html"] = """{% extends 'base.html' %}{% block c %}<h1>{{titulo}}</h1><div class="card"><form method="post">""" + HID + """
{% for k,l,t in fields %}<label for="{{k}}">{{l}}</label>{% if t is string %}<input id="{{k}}" name="{{k}}" type="{{t}}" value="{{v[k] or ''}}">
{% else %}<select id="{{k}}" name="{{k}}">{% for o in t %}<option {{'selected' if v[k]==o}}>{{o}}</option>{% endfor %}</select>{% endif %}{% endfor %}
<p><button>Guardar</button> <a class="btn sec" href="/{{back}}">Cancelar</a></p></form></div>{% endblock %}"""
T["caps.html"] = """{% extends 'base.html' %}{% block c %}<h1>Capacitaciones</h1>{% if session.rol=='admin' %}<p><a class="btn" href="/capacitaciones/nueva">Nueva capacitación</a></p>{% endif %}
<div class="card"><table><tr><th>Nombre</th><th>Fecha</th><th>Modalidad</th><th>Cupos</th><th>Estado</th></tr>
{% for c in rows %}<tr><td><a href="/capacitaciones/{{c.id_capacitacion}}">{{c.nombre}}</a></td><td>{{c.fecha_hora.replace('T',' ')}}</td><td>{{c.modalidad}}</td>
<td>{{c.ins}}/{{c.cupos_totales}}</td><td>{{c.estado}}</td></tr>{% else %}<tr><td colspan="5" class="mut">Aún no hay capacitaciones registradas.</td></tr>{% endfor %}</table></div>{% endblock %}"""
T["cap.html"] = """{% extends 'base.html' %}{% block c %}<h1>{{c.nombre}}</h1><div class="card"><p>{{c.tema or 'Sin tema'}} · {{c.modalidad}}: {{c.lugar_enlace}}<br>
{{c.fecha_hora.replace('T',' ')}} · {{c.estado}} · <b>{{disp}}</b> cupos disponibles de {{c.cupos_totales}}</p>
{% if session.rol=='admin' %}<a class="btn sec" href="/capacitaciones/{{c.id_capacitacion}}/editar">Editar</a>{% endif %}</div>
{% if session.rol=='admin' and c.estado=='Programada' and disp>0 and libres %}<div class="card"><h2>Inscribir participante</h2>
<form method="post" action="/capacitaciones/{{c.id_capacitacion}}/inscribir">""" + HID + """<select name="pid" aria-label="Participante">
{% for p in libres %}<option value="{{p.id_participante}}">{{p.apellidos}}, {{p.nombres}} ({{p.numero_identificacion}})</option>{% endfor %}</select>
<p><button>Inscribir</button></p></form></div>{% endif %}
<div class="card"><h2>Inscritos y asistencia</h2>{% if ins %}<form method="post" action="/capacitaciones/{{c.id_capacitacion}}/asistencia">""" + HID + """
<table><tr><th>Participante</th><th>Identificación</th><th>Asistencia</th><th></th></tr>{% for i in ins %}<tr><td>{{i.nom}}</td><td>{{i.ident}}</td>
<td><select name="a_{{i.id_inscripcion}}" aria-label="Asistencia de {{i.nom}}">{% for e in est %}<option {{'selected' if i.estado==e}}>{{e}}</option>{% endfor %}</select></td>
<td>{% if session.rol=='admin' %}<button class="del" formaction="/inscripciones/{{i.id_inscripcion}}/cancelar" formnovalidate>Cancelar inscripción</button>{% endif %}</td></tr>{% endfor %}</table>
<p><button>Guardar asistencia</button></p></form>{% else %}<p class="mut">Todavía no hay inscritos.</p>{% endif %}</div>{% endblock %}"""
T["pars.html"] = """{% extends 'base.html' %}{% block c %}<h1>Participantes</h1><form method="get" class="row" style="align-items:end"><div><label for="q">Buscar</label>
<input id="q" name="q" value="{{request.args.q or ''}}" placeholder="Nombre, identificación o empresa"></div><button class="sec">Buscar</button>
{% if session.rol=='admin' %}<a class="btn" href="/participantes/nuevo">Nuevo participante</a>{% endif %}</form><div class="card" style="margin-top:1rem"><table>
<tr><th>Nombre</th><th>Identificación</th><th>Correo</th><th>Empresa</th><th></th></tr>{% for p in rows %}<tr><td>{{p.nombres}} {{p.apellidos}}</td><td>{{p.numero_identificacion}}</td>
<td>{{p.correo}}</td><td>{{p.empresa or ''}}</td><td>{% if session.rol=='admin' %}<a href="/participantes/{{p.id_participante}}/editar">Editar</a>{% endif %}</td></tr>
{% else %}<tr><td colspan="5" class="mut">No se encontraron participantes.</td></tr>{% endfor %}</table></div>{% endblock %}"""
T["rep.html"] = """{% extends 'base.html' %}{% block c %}<h1>Reportes</h1><div class="card"><h2>Asistencia por capacitación</h2><table>
<tr><th>Capacitación</th><th>Estado</th><th>Inscritos</th><th>Asistieron</th><th>No asistieron</th></tr>{% for r in res %}<tr><td>
<a href="/capacitaciones/{{r.id_capacitacion}}">{{r.nombre}}</a></td><td>{{r.estado}}</td><td>{{r.inscritos}}/{{r.cupos_totales}}</td><td>{{r.asistieron}}</td><td>{{r.no_asistieron}}</td></tr>
{% else %}<tr><td colspan="5" class="mut">Sin datos todavía.</td></tr>{% endfor %}</table><p><a class="btn sec" href="/reportes.csv">Descargar CSV</a></p></div>
<div class="card"><h2>Historial de un participante</h2><form method="get"><select name="pid" aria-label="Participante">{% for p in pars %}
<option value="{{p.id_participante}}" {{'selected' if pid|string==p.id_participante|string}}>{{p.apellidos}}, {{p.nombres}}</option>{% endfor %}</select> <button>Ver historial</button></form>
{% if pid %}<table><tr><th>Capacitación</th><th>Fecha</th><th>Asistencia</th></tr>{% for h in hist %}<tr><td>{{h.nombre}}</td><td>{{h.fecha_hora.replace('T',' ')}}</td><td>{{h.estado}}</td></tr>
{% else %}<tr><td colspan="3" class="mut">Este participante no tiene inscripciones.</td></tr>{% endfor %}</table>{% endif %}</div>{% endblock %}"""
app.jinja_loader = DictLoader(T)
init_db()
if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 8000)))
