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
                CREATE TABLE IF NOT EXISTS chats (
                    id SERIAL PRIMARY KEY,
                    photo TEXT,
                    nom TEXT,
                    couleur TEXT,
                    race TEXT,
                    sexe TEXT,
                    proprietaire TEXT,
                    tel_proprietaire TEXT,
                    comportements TEXT,
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
            folder="chats-voisinage",
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


def parse_tags(raw):
    return [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]


def tags_to_str(raw):
    return ", ".join(parse_tags(raw))


@app.route("/")
def index():
    search = request.args.get("q", "").strip()
    race = request.args.get("race", "").strip()
    sexe = request.args.get("sexe", "").strip()
    comportement = request.args.get("comportement", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 24

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions = []
            params = []

            if search:
                conditions.append("(nom ILIKE %s OR couleur ILIKE %s OR race ILIKE %s OR proprietaire ILIKE %s OR notes ILIKE %s)")
                params += [f"%{search}%"] * 5
            if race:
                conditions.append("race ILIKE %s")
                params.append(f"%{race}%")
            if sexe:
                conditions.append("sexe = %s")
                params.append(sexe)
            if comportement:
                conditions.append("comportements ILIKE %s")
                params.append(f"%{comportement}%")

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(f"SELECT COUNT(*) as n FROM chats {where}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"SELECT * FROM chats {where} ORDER BY nom ASC LIMIT %s OFFSET %s",
                params + [per_page, (page - 1) * per_page]
            )
            items = cur.fetchall()

            cur.execute("SELECT DISTINCT race FROM chats WHERE race != '' ORDER BY race")
            races = [r["race"] for r in cur.fetchall()]

            cur.execute("SELECT comportements FROM chats WHERE comportements != ''")
            all_tags = set()
            for r in cur.fetchall():
                for t in parse_tags(r["comportements"]):
                    all_tags.add(t)
            comportements = sorted(all_tags)

    total_pages = (total + per_page - 1) // per_page

    return render_template("index.html",
        items=items, total=total, page=page, total_pages=total_pages,
        races=races, comportements=comportements,
        search=search, race=race, sexe=sexe, comportement=comportement,
        parse_tags=parse_tags
    )


@app.route("/ajouter", methods=["GET", "POST"])
def ajouter():
    if request.method == "POST":
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chats (photo, nom, couleur, race, sexe, proprietaire, tel_proprietaire, comportements, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    upload_field("photo"),
                    request.form.get("nom", "").strip(),
                    request.form.get("couleur", "").strip(),
                    request.form.get("race", "").strip(),
                    request.form.get("sexe", ""),
                    request.form.get("proprietaire", "").strip(),
                    request.form.get("tel_proprietaire", "").strip(),
                    tags_to_str(request.form.get("comportements", "")),
                    request.form.get("notes", "").strip(),
                ))
        flash("Chat ajouté avec succès !", "success")
        return redirect(url_for("index"))

    return render_template("form.html", item=None, action="Ajouter")


@app.route("/fiche/<int:item_id>")
def fiche(item_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM chats WHERE id = %s", (item_id,))
            item = cur.fetchone()
    if not item:
        flash("Chat introuvable.", "danger")
        return redirect(url_for("index"))
    return render_template("fiche.html", item=item, parse_tags=parse_tags)


@app.route("/modifier/<int:item_id>", methods=["GET", "POST"])
def modifier(item_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM chats WHERE id = %s", (item_id,))
            item = cur.fetchone()
    if not item:
        return redirect(url_for("index"))

    if request.method == "POST":
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE chats SET photo=%s, nom=%s, couleur=%s, race=%s, sexe=%s,
                    proprietaire=%s, tel_proprietaire=%s, comportements=%s, notes=%s
                    WHERE id=%s
                """, (
                    upload_field("photo", item["photo"]),
                    request.form.get("nom", "").strip(),
                    request.form.get("couleur", "").strip(),
                    request.form.get("race", "").strip(),
                    request.form.get("sexe", ""),
                    request.form.get("proprietaire", "").strip(),
                    request.form.get("tel_proprietaire", "").strip(),
                    tags_to_str(request.form.get("comportements", "")),
                    request.form.get("notes", "").strip(),
                    item_id,
                ))
        flash("Fiche modifiée.", "success")
        return redirect(url_for("fiche", item_id=item_id))

    return render_template("form.html", item=item, action="Modifier")


@app.route("/supprimer/<int:item_id>", methods=["POST"])
def supprimer(item_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chats WHERE id = %s", (item_id,))
    flash("Chat supprimé.", "warning")
    return redirect(url_for("index"))


@app.route("/stats")
def stats():
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) as n FROM chats")
            total = cur.fetchone()["n"]
            cur.execute("SELECT race, COUNT(*) as n FROM chats WHERE race != '' GROUP BY race ORDER BY n DESC LIMIT 15")
            par_race = cur.fetchall()
            cur.execute("SELECT sexe, COUNT(*) as n FROM chats WHERE sexe != '' GROUP BY sexe")
            par_sexe = cur.fetchall()
            cur.execute("SELECT comportements FROM chats WHERE comportements != ''")
            tag_count = {}
            for r in cur.fetchall():
                for t in parse_tags(r["comportements"]):
                    tag_count[t] = tag_count.get(t, 0) + 1
            par_comportement = sorted(tag_count.items(), key=lambda x: -x[1])[:15]

    return render_template("stats.html", total=total,
        par_race=par_race, par_sexe=par_sexe, par_comportement=par_comportement)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
