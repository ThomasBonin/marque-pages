import os
import io
import sqlite3
import cloudinary
import cloudinary.uploader
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "changeme-in-production")

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

DB_PATH = os.environ.get("DB_PATH", "bookmarks.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS marque_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_recto TEXT,
                photo_verso TEXT,
                annee TEXT,
                editeur TEXT,
                theme TEXT,
                pays TEXT,
                etat TEXT,
                quantite INTEGER DEFAULT 1,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_to_cloudinary(file_storage):
    """Redimensionne puis uploade vers Cloudinary, retourne l'URL publique."""
    try:
        img = Image.open(file_storage)
        img.thumbnail((1200, 1200))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=82)
        buf.seek(0)
        result = cloudinary.uploader.upload(
            buf,
            folder="marque-pages",
            transformation={"quality": "auto", "fetch_format": "auto"},
        )
        return result["secure_url"]
    except Exception as e:
        app.logger.error(f"Cloudinary upload error: {e}")
        return None


def upload_field(field_name, fallback=None):
    if field_name in request.files:
        f = request.files[field_name]
        if f and f.filename and allowed_file(f.filename):
            return upload_to_cloudinary(f)
    return fallback


@app.route("/")
def index():
    search = request.args.get("q", "").strip()
    annee = request.args.get("annee", "").strip()
    editeur = request.args.get("editeur", "").strip()
    theme = request.args.get("theme", "").strip()
    pays = request.args.get("pays", "").strip()
    etat = request.args.get("etat", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 24

    with get_db() as conn:
        conditions = []
        params = []

        if search:
            conditions.append("(editeur LIKE ? OR theme LIKE ? OR pays LIKE ? OR notes LIKE ?)")
            params += [f"%{search}%"] * 4
        if annee:
            conditions.append("annee = ?")
            params.append(annee)
        if editeur:
            conditions.append("editeur LIKE ?")
            params.append(f"%{editeur}%")
        if theme:
            conditions.append("theme LIKE ?")
            params.append(f"%{theme}%")
        if pays:
            conditions.append("pays LIKE ?")
            params.append(f"%{pays}%")
        if etat:
            conditions.append("etat = ?")
            params.append(etat)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total = conn.execute(f"SELECT COUNT(*) FROM marque_pages {where}", params).fetchone()[0]
        items = conn.execute(
            f"SELECT * FROM marque_pages {where} ORDER BY annee DESC, editeur ASC LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page]
        ).fetchall()

        annees = [r[0] for r in conn.execute("SELECT DISTINCT annee FROM marque_pages WHERE annee != '' ORDER BY annee DESC").fetchall()]
        editeurs = [r[0] for r in conn.execute("SELECT DISTINCT editeur FROM marque_pages WHERE editeur != '' ORDER BY editeur").fetchall()]
        themes = [r[0] for r in conn.execute("SELECT DISTINCT theme FROM marque_pages WHERE theme != '' ORDER BY theme").fetchall()]
        pays_list = [r[0] for r in conn.execute("SELECT DISTINCT pays FROM marque_pages WHERE pays != '' ORDER BY pays").fetchall()]

    total_pages = (total + per_page - 1) // per_page

    return render_template("index.html",
        items=items, total=total, page=page, total_pages=total_pages,
        annees=annees, editeurs=editeurs, themes=themes, pays_list=pays_list,
        search=search, annee=annee, editeur=editeur, theme=theme, pays=pays, etat=etat
    )


@app.route("/ajouter", methods=["GET", "POST"])
def ajouter():
    if request.method == "POST":
        with get_db() as conn:
            conn.execute("""
                INSERT INTO marque_pages (photo_recto, photo_verso, annee, editeur, theme, pays, etat, quantite, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                upload_field("photo_recto"),
                upload_field("photo_verso"),
                request.form.get("annee", "").strip(),
                request.form.get("editeur", "").strip(),
                request.form.get("theme", "").strip(),
                request.form.get("pays", "").strip(),
                request.form.get("etat", ""),
                int(request.form.get("quantite", 1) or 1),
                request.form.get("notes", "").strip(),
            ))
        flash("Marque-page ajouté avec succès !", "success")
        return redirect(url_for("index"))

    return render_template("form.html", item=None, action="Ajouter")


@app.route("/fiche/<int:item_id>")
def fiche(item_id):
    with get_db() as conn:
        item = conn.execute("SELECT * FROM marque_pages WHERE id = ?", (item_id,)).fetchone()
    if not item:
        flash("Marque-page introuvable.", "danger")
        return redirect(url_for("index"))
    return render_template("fiche.html", item=item)


@app.route("/modifier/<int:item_id>", methods=["GET", "POST"])
def modifier(item_id):
    with get_db() as conn:
        item = conn.execute("SELECT * FROM marque_pages WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return redirect(url_for("index"))

    if request.method == "POST":
        with get_db() as conn:
            conn.execute("""
                UPDATE marque_pages SET photo_recto=?, photo_verso=?, annee=?, editeur=?, theme=?, pays=?, etat=?, quantite=?, notes=?
                WHERE id=?
            """, (
                upload_field("photo_recto", item["photo_recto"]),
                upload_field("photo_verso", item["photo_verso"]),
                request.form.get("annee", "").strip(),
                request.form.get("editeur", "").strip(),
                request.form.get("theme", "").strip(),
                request.form.get("pays", "").strip(),
                request.form.get("etat", ""),
                int(request.form.get("quantite", 1) or 1),
                request.form.get("notes", "").strip(),
                item_id,
            ))
        flash("Marque-page modifié.", "success")
        return redirect(url_for("fiche", item_id=item_id))

    return render_template("form.html", item=item, action="Modifier")


@app.route("/supprimer/<int:item_id>", methods=["POST"])
def supprimer(item_id):
    with get_db() as conn:
        conn.execute("DELETE FROM marque_pages WHERE id = ?", (item_id,))
    flash("Marque-page supprimé.", "warning")
    return redirect(url_for("index"))


@app.route("/stats")
def stats():
    with get_db() as conn:
        total = conn.execute("SELECT SUM(quantite) FROM marque_pages").fetchone()[0] or 0
        nb_fiches = conn.execute("SELECT COUNT(*) FROM marque_pages").fetchone()[0]
        par_annee = conn.execute("SELECT annee, COUNT(*) as n FROM marque_pages WHERE annee != '' GROUP BY annee ORDER BY annee").fetchall()
        par_theme = conn.execute("SELECT theme, COUNT(*) as n FROM marque_pages WHERE theme != '' GROUP BY theme ORDER BY n DESC LIMIT 15").fetchall()
        par_pays = conn.execute("SELECT pays, COUNT(*) as n FROM marque_pages WHERE pays != '' GROUP BY pays ORDER BY n DESC LIMIT 15").fetchall()
        par_editeur = conn.execute("SELECT editeur, COUNT(*) as n FROM marque_pages WHERE editeur != '' GROUP BY editeur ORDER BY n DESC LIMIT 15").fetchall()
    return render_template("stats.html", total=total, nb_fiches=nb_fiches,
        par_annee=par_annee, par_theme=par_theme, par_pays=par_pays, par_editeur=par_editeur)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
