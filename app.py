import os
import io
import cloudinary
import cloudinary.uploader
import psycopg2
import psycopg2.extras
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "changeme-in-production")

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

DB_URL = os.environ.get("DATABASE_URL")


def get_db():
    conn = psycopg2.connect(DB_URL)
    return conn


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS marque_pages (
                    id SERIAL PRIMARY KEY,
                    photo_recto TEXT,
                    photo_verso TEXT,
                    annee TEXT,
                    editeur TEXT,
                    themes TEXT,
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


def parse_themes(raw):
    """Nettoie et retourne une liste de thèmes depuis une chaîne."""
    return [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]


def themes_to_str(raw):
    return ", ".join(parse_themes(raw))


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
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions = []
            params = []

            if search:
                conditions.append("(editeur ILIKE %s OR themes ILIKE %s OR pays ILIKE %s OR notes ILIKE %s)")
                params += [f"%{search}%"] * 4
            if annee:
                conditions.append("annee = %s")
                params.append(annee)
            if editeur:
                conditions.append("editeur ILIKE %s")
                params.append(f"%{editeur}%")
            if theme:
                conditions.append("themes ILIKE %s")
                params.append(f"%{theme}%")
            if pays:
                conditions.append("pays ILIKE %s")
                params.append(f"%{pays}%")
            if etat:
                conditions.append("etat = %s")
                params.append(etat)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(f"SELECT COUNT(*) as n FROM marque_pages {where}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"SELECT * FROM marque_pages {where} ORDER BY annee DESC, editeur ASC LIMIT %s OFFSET %s",
                params + [per_page, (page - 1) * per_page]
            )
            items = cur.fetchall()

            cur.execute("SELECT DISTINCT annee FROM marque_pages WHERE annee != '' ORDER BY annee DESC")
            annees = [r["annee"] for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT editeur FROM marque_pages WHERE editeur != '' ORDER BY editeur")
            editeurs = [r["editeur"] for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT pays FROM marque_pages WHERE pays != '' ORDER BY pays")
            pays_list = [r["pays"] for r in cur.fetchall()]

            # Thèmes : extraire tous les tags individuels
            cur.execute("SELECT themes FROM marque_pages WHERE themes != ''")
            all_themes = set()
            for r in cur.fetchall():
                for t in parse_themes(r["themes"]):
                    all_themes.add(t)
            themes = sorted(all_themes)

    total_pages = (total + per_page - 1) // per_page

    return render_template("index.html",
        items=items, total=total, page=page, total_pages=total_pages,
        annees=annees, editeurs=editeurs, themes=themes, pays_list=pays_list,
        search=search, annee=annee, editeur=editeur, theme=theme, pays=pays, etat=etat,
        parse_themes=parse_themes
    )


@app.route("/ajouter", methods=["GET", "POST"])
def ajouter():
    if request.method == "POST":
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO marque_pages (photo_recto, photo_verso, annee, editeur, themes, pays, etat, quantite, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    upload_field("photo_recto"),
                    upload_field("photo_verso"),
                    request.form.get("annee", "").strip(),
                    request.form.get("editeur", "").strip(),
                    themes_to_str(request.form.get("themes", "")),
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
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM marque_pages WHERE id = %s", (item_id,))
            item = cur.fetchone()
    if not item:
        flash("Marque-page introuvable.", "danger")
        return redirect(url_for("index"))
    return render_template("fiche.html", item=item, parse_themes=parse_themes)


@app.route("/modifier/<int:item_id>", methods=["GET", "POST"])
def modifier(item_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM marque_pages WHERE id = %s", (item_id,))
            item = cur.fetchone()
    if not item:
        return redirect(url_for("index"))

    if request.method == "POST":
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE marque_pages SET photo_recto=%s, photo_verso=%s, annee=%s, editeur=%s,
                    themes=%s, pays=%s, etat=%s, quantite=%s, notes=%s WHERE id=%s
                """, (
                    upload_field("photo_recto", item["photo_recto"]),
                    upload_field("photo_verso", item["photo_verso"]),
                    request.form.get("annee", "").strip(),
                    request.form.get("editeur", "").strip(),
                    themes_to_str(request.form.get("themes", "")),
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
        with conn.cursor() as cur:
            cur.execute("DELETE FROM marque_pages WHERE id = %s", (item_id,))
    flash("Marque-page supprimé.", "warning")
    return redirect(url_for("index"))


@app.route("/stats")
def stats():
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(SUM(quantite),0) as n FROM marque_pages")
            total = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) as n FROM marque_pages")
            nb_fiches = cur.fetchone()["n"]
            cur.execute("SELECT annee, COUNT(*) as n FROM marque_pages WHERE annee != '' GROUP BY annee ORDER BY annee")
            par_annee = cur.fetchall()
            cur.execute("SELECT pays, COUNT(*) as n FROM marque_pages WHERE pays != '' GROUP BY pays ORDER BY n DESC LIMIT 15")
            par_pays = cur.fetchall()
            cur.execute("SELECT editeur, COUNT(*) as n FROM marque_pages WHERE editeur != '' GROUP BY editeur ORDER BY n DESC LIMIT 15")
            par_editeur = cur.fetchall()
            # Compter les thèmes individuels
            cur.execute("SELECT themes FROM marque_pages WHERE themes != ''")
            theme_count = {}
            for r in cur.fetchall():
                for t in parse_themes(r["themes"]):
                    theme_count[t] = theme_count.get(t, 0) + 1
            par_theme = sorted(theme_count.items(), key=lambda x: -x[1])[:15]

    return render_template("stats.html", total=total, nb_fiches=nb_fiches,
        par_annee=par_annee, par_theme=par_theme, par_pays=par_pays, par_editeur=par_editeur)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
