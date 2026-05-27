#!/usr/bin/env python3

"""
TiddlyWiki -> Anki (.apkg) exporter

Supports:
- TiddlyWiki JSON export
- MathJax ($$ ... $$)
- [[Wiki Links]]
- [img[image.png]]
- Safe HTML escaping
- Embedded media
- Stable note GUIDs
- Proper formatting in Anki

Usage:
    python tw_to_anki.py wiki.json

Requirements:
    pip install genanki beautifulsoup4
"""

import json
import re
import sys
import html
import hashlib
from pathlib import Path

import genanki
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

DECK_NAME = "MCS"

OUTPUT_FILE = "tiddlywiki.apkg"

MEDIA_DIR = Path("./tiddlers")

SKIP_SYSTEM_TIDDLERS = True


# ============================================================
# ANKI MODEL
# ============================================================

MODEL_ID = 847362514
DECK_ID = 927451223

model = genanki.Model(
    MODEL_ID,
    "TiddlyWiki Basic",
    fields=[
        {"name": "Front"},
        {"name": "Back"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": """
<div class="front">
{{Front}}
</div>
""",
            "afmt": """
{{FrontSide}}

<hr id="answer">

<div class="back">
{{Back}}
</div>
""",
        }
    ],
    css="""
card {
    font-family: Arial;
    font-size: 20px;
    text-align: left;
    color: black;
    background-color: white;
    padding: 20px;
}

.front {
    font-size: 30px;
    font-weight: bold;
    margin-bottom: 20px;
}

.back {
    line-height: 1.6;
}

img {
    max-width: 100%;
    height: auto;
    margin-top: 10px;
}

pre {
    background: #f5f5f5;
    padding: 10px;
    overflow-x: auto;
}

code {
    background: #f0f0f0;
    padding: 2px 4px;
}

p {
    margin-top: 0.8em;
    margin-bottom: 0.8em;
}
""",
)

deck = genanki.Deck(DECK_ID, DECK_NAME)


# ============================================================
# HELPERS
# ============================================================

def stable_guid(title):
    """
    Stable GUID prevents duplicate cards on re-import.
    """
    return hashlib.md5(title.encode("utf-8")).hexdigest()


# ============================================================
# MATH HANDLING
# ============================================================

def extract_math(text):
    """
    Extract $$...$$ blocks before escaping HTML.
    """

    math_store = {}

    def repl(match):

        content = match.group(1).strip()

        key = f"@@MATH{len(math_store)}@@"

        # Convert to Anki-compatible MathJax
        math_store[key] = f"\\({content}\\)"

        return key

    text = re.sub(
        r"\$\$(.*?)\$\$",
        repl,
        text,
        flags=re.DOTALL,
    )

    return text, math_store

def restore_math(text, math_store):

    for key, value in math_store.items():
        text = text.replace(key, value)

    return text


# ============================================================
# TIDDLYWIKI MARKUP
# ============================================================

def convert_wikilinks(text):
    """
    [[Foo]] -> bold text
    """

    pattern = r"\[\[(.*?)\]\]"

    return re.sub(
        pattern,
        r"<b>\1</b>",
        text,
    )


def convert_image_embeds(text):
    """
    [img[foo.png]] -> <img src="foo.png">
    """

    media = []

    def repl(match):

        filename = match.group(1).strip()

        media.append(filename)

        return f'<img src="{filename}">'

    text = re.sub(
        r"\[img\[(.*?)\]\]",
        repl,
        text,
    )

    return text, media


def convert_linebreaks(text):
    """
    Convert linebreaks into HTML paragraphs.
    """

    paragraphs = text.split("\n\n")

    rendered = []

    for p in paragraphs:

        p = p.replace("\n", "<br>")

        rendered.append(f"<p>{p}</p>")

    return "\n".join(rendered)


# ============================================================
# MEDIA
# ============================================================

def collect_html_images(html_text):

    soup = BeautifulSoup(html_text, "html.parser")

    media = []

    for img in soup.find_all("img"):

        src = img.get("src")

        if src:
            media.append(src)

    return media


# ============================================================
# RENDERER
# ============================================================

def render_tiddler(text):
    """
    Safe TiddlyWiki -> HTML renderer.
    """

    # --------------------------------------------------------
    # preserve math
    # --------------------------------------------------------

    text, math_store = extract_math(text)

    # --------------------------------------------------------
    # escape everything
    # --------------------------------------------------------

    text = html.escape(text)

    # --------------------------------------------------------
    # restore supported constructs
    # --------------------------------------------------------

    text, image_media = convert_image_embeds(text)

    text = convert_wikilinks(text)

    text = convert_linebreaks(text)

    # --------------------------------------------------------
    # restore math
    # --------------------------------------------------------

    text = restore_math(text, math_store)

    # --------------------------------------------------------
    # media discovery
    # --------------------------------------------------------

    html_media = collect_html_images(text)

    media = set(image_media + html_media)

    return text, media


# ============================================================
# MAIN
# ============================================================

if len(sys.argv) < 2:

    print("Usage:")
    print("    python tw_to_anki.py wiki.json")

    sys.exit(1)


json_path = Path(sys.argv[1])

if not json_path.exists():

    print(f"Missing file: {json_path}")

    sys.exit(1)


with open(json_path, "r", encoding="utf-8") as f:

    tiddlers = json.load(f)


# ============================================================
# BUILD DECK
# ============================================================

all_media = set()

count = 0

for tiddler in tiddlers:

    title = tiddler.get("title", "").strip()

    if not title:
        continue

    # Skip TW internals
    if SKIP_SYSTEM_TIDDLERS and title.startswith("$:/"):
        continue

    text = tiddler.get("text", "")

    back_html, media = render_tiddler(text)

    all_media.update(media)

    note = genanki.Note(
        model=model,
        fields=[
            title,
            back_html,
        ],
        guid=stable_guid(title),
    )

    deck.add_note(note)

    count += 1


# ============================================================
# MEDIA RESOLUTION
# ============================================================

media_files = []

missing_media = []

for media_name in sorted(all_media):

    # Ignore remote images
    if media_name.startswith("http://"):
        continue

    if media_name.startswith("https://"):
        continue

    media_path = MEDIA_DIR / media_name

    if media_path.exists():

        media_files.append(str(media_path))

    else:

        missing_media.append(media_name)


if missing_media:

    print("\nMissing media files:")

    for m in missing_media:
        print(f"  - {m}")


# ============================================================
# EXPORT
# ============================================================

package = genanki.Package(deck)

package.media_files = media_files

package.write_to_file(OUTPUT_FILE)


# ============================================================
# DONE
# ============================================================

print("\nDone.")

print(f"\nCreated:")
print(f"  {OUTPUT_FILE}")

print(f"\nNotes:")
print(f"  {count}")

print(f"\nMedia files:")
print(f"  {len(media_files)}")