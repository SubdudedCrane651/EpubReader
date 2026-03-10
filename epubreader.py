import sys
import os
import base64
import sqlite3
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextBrowser, QFileDialog, QListWidget, QSplitter, QComboBox,
    QMainWindow, QAction, QSizePolicy
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import os
os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts=false"

class EpubReader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EPUB Reader (Python Version)")
        self.resize(1000, 700)

        self.chapters = []
        self.pages = []
        self.current_chapter = 0
        self.current_page = 0
        self.font_size = 14
        self.cover_data = None
        self.current_book = None
        self.images = {}
        self.book = None
        self.toc_map = {}

        self.suppress_load = False

        # ⭐ FIXED: Always store DB in AppData (works in .exe)
        appdata = Path(os.getenv("LOCALAPPDATA")) / "EpubReader"
        appdata.mkdir(parents=True, exist_ok=True)
        self.db_path = str(appdata / "reader.db")

        self.init_database()

        # UI SETUP
        menu = self.menuBar()
        file_menu = menu.addMenu("File")

        open_action = QAction("Open EPUB", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_epub)
        file_menu.addAction(open_action)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)

        self.chapter_list = QListWidget()
        self.chapter_list.currentRowChanged.connect(self.load_chapter)
        splitter.addWidget(self.chapter_list)

        self.text_view = QTextBrowser()
        self.text_view.setFont(QFont("Times New Roman", self.font_size))
        self.text_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        splitter.addWidget(self.text_view)

        splitter.setSizes([200, 800])
        main_layout.addWidget(splitter)

        controls = QHBoxLayout()

        open_btn = QPushButton("Open EPUB")
        open_btn.clicked.connect(self.open_epub)
        controls.addWidget(open_btn)

        prev_btn = QPushButton("◀ Prev Page")
        prev_btn.clicked.connect(self.prev_page)
        controls.addWidget(prev_btn)

        next_btn = QPushButton("Next Page ▶")
        next_btn.clicked.connect(self.next_page)
        controls.addWidget(next_btn)

        bigger_btn = QPushButton("A+")
        bigger_btn.clicked.connect(self.increase_font)
        controls.addWidget(bigger_btn)

        smaller_btn = QPushButton("A-")
        smaller_btn.clicked.connect(self.decrease_font)
        controls.addWidget(smaller_btn)

        self.font_selector = QComboBox()
        self.font_selector.addItems(["Times New Roman", "Arial", "Calibri", "Courier New"])
        self.font_selector.currentTextChanged.connect(self.change_font_family)
        controls.addWidget(self.font_selector)

        main_layout.addLayout(controls)

    # DATABASE
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS progress (
                book_path TEXT PRIMARY KEY,
                chapter INTEGER,
                page INTEGER
            )
        """)
        conn.commit()
        conn.close()

    def save_progress(self, book_path, chapter, page):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO progress (book_path, chapter, page)
            VALUES (?, ?, ?)
            ON CONFLICT(book_path) DO UPDATE SET
                chapter=excluded.chapter,
                page=excluded.page
        """, (book_path, chapter, page))
        conn.commit()
        conn.close()

    def load_progress(self, book_path):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT chapter, page FROM progress WHERE book_path=?", (book_path,))
        row = cur.fetchone()
        conn.close()
        return row if row else (0, 0)

    # EPUB LOADING
    def open_epub(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select EPUB File", "", "EPUB Files (*.epub)"
        )
        if file_path:
            self.load_epub(file_path)

    def build_toc_map(self, toc):
        for entry in toc:
            if isinstance(entry, epub.Link):
                href = entry.href.split("#")[0]
                self.toc_map[href] = entry.title.strip()
            elif isinstance(entry, tuple):
                item, children = entry
                if isinstance(item, epub.Link):
                    href = item.href.split("#")[0]
                    self.toc_map[href] = item.title.strip()
                if children:
                    self.build_toc_map(children)

    def extract_title(self, item, default_title):
        href = item.get_name().split("#")[0]
        if href in self.toc_map:
            return self.toc_map[href]

        soup = BeautifulSoup(item.get_content(), "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()

        return default_title

    def load_epub(self, path):
        self.current_book = os.path.abspath(path)
        self.book = epub.read_epub(path)

        self.chapters.clear()
        self.chapter_list.clear()
        self.cover_data = None
        self.images.clear()
        self.toc_map = {}

        self.build_toc_map(self.book.toc)

        # Load images
        for item in self.book.get_items():
            if item.get_type() == ebooklib.ITEM_IMAGE:
                self.images[item.get_name()] = item.get_content()

        # Load cover.jpg from same folder
        cover_path = os.path.join(os.path.dirname(path), "cover.jpg")
        if os.path.exists(cover_path):
            with open(cover_path, "rb") as f:
                self.cover_data = f.read()

        chapter_counter = 1

        for item in self.book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                html = self.embed_images(str(soup))
                if html.strip():
                    title = self.extract_title(item, f"Chapter {chapter_counter}")
                    self.chapters.append(html)
                    self.chapter_list.addItem(title)
                    chapter_counter += 1

        if self.cover_data:
            self.chapters.insert(0, "__COVER__")
            self.chapter_list.insertItem(0, "Cover Page")

        chapter, page = self.load_progress(self.current_book)

        self.suppress_load = True
        self.chapter_list.setCurrentRow(chapter)
        self.current_chapter = chapter
        self.current_page = page
        self.suppress_load = False

        self.load_chapter(chapter)
        self.current_page = min(page, len(self.pages) - 1)
        self.display_page()

    def embed_images(self, html):
        soup = BeautifulSoup(html, "html.parser")

        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue

            key = src.split("/")[-1]

            for stored_key, data in self.images.items():
                if stored_key.endswith(key):
                    b64 = base64.b64encode(data).decode("ascii")
                    img["src"] = f"data:image/jpeg;base64,{b64}"
                    break

        return str(soup)

    # PAGINATION
    def paginate_chapter(self, html):
        soup = BeautifulSoup(html, "html.parser")

        blocks = []
        for elem in soup.find_all(["p", "div", "img", "h1", "h2", "h3", "h4"]):
            blocks.append(str(elem))

        pages = []
        current = []
        length = 0
        max_length = 1800

        for block in blocks:
            block_len = len(block)

            if length + block_len > max_length and current:
                pages.append("".join(current))
                current = []
                length = 0

            current.append(block)
            length += block_len

        if current:
            pages.append("".join(current))

        return pages

    # CHAPTER + PAGE HANDLING
    def load_chapter(self, index):
        if self.suppress_load:
            return

        if index < 0 or index >= len(self.chapters):
            return

        if self.current_book:
            self.save_progress(self.current_book, index, 0)

        if self.chapters[index] == "__COVER__" and self.cover_data:
            b64 = base64.b64encode(self.cover_data).decode("ascii")
            html = f"""
            <html>
            <body style="background-color:#202020;">
                <div style="text-align:center; margin-top:20px;">
                    <img src="data:image/jpeg;base64,{b64}" style="max-width:90%; max-height:90%;" />
                </div>
            </body>
            </html>
            """
            self.text_view.setHtml(html)
            self.pages = []
            self.current_chapter = index
            self.current_page = 0
            return

        self.current_chapter = index
        chapter_html = self.chapters[index]

        self.pages = self.paginate_chapter(chapter_html)

        _, saved_page = self.load_progress(self.current_book)
        self.current_page = min(saved_page, len(self.pages) - 1)

        self.display_page()

    def display_page(self):
        if self.pages:
            text = self.pages[self.current_page]
            total = len(self.pages)
            current = self.current_page + 1

            html = f"""
            <html>
            <body>
            <div>{text}</div>
            <div style="text-align:center; margin-top:20px; font-weight:bold;">
                Page {current} / {total}
            </div>
            </body>
            </html>
            """

            self.text_view.setHtml(html)

            if self.current_book:
                self.save_progress(self.current_book, self.current_chapter, self.current_page)

    def next_page(self):
        if self.pages and self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self.display_page()

    def prev_page(self):
        if self.pages and self.current_page > 0:
            self.current_page -= 1
            self.display_page()

    # FONT CONTROLS
    def increase_font(self):
        self.font_size += 2
        self.text_view.setFont(QFont(self.font_selector.currentText(), self.font_size))

    def decrease_font(self):
        if self.font_size > 6:
            self.font_size -= 2
            self.text_view.setFont(QFont(self.font_selector.currentText(), self.font_size))

    def change_font_family(self, family):
        self.text_view.setFont(QFont(family, self.font_size))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    reader = EpubReader()
    reader.show()

    # ⭐ FIXED: Double-click .epub support for .exe
    if len(sys.argv) > 1:
        epub_path = sys.argv[1]
        if os.path.exists(epub_path) and epub_path.lower().endswith(".epub"):
            reader.load_epub(epub_path)

    sys.exit(app.exec_())