from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import os

app = FastAPI(title="Book Summary")

# Setup paths
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

# Mount static files
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static")

# Setup templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_books():
    """Get list of all available books"""
    books = []
    if not OUTPUT_DIR.exists():
        return books

    for book_dir in OUTPUT_DIR.iterdir():
        if book_dir.is_dir():
            view_file = book_dir / "view" / "view.html"
            if view_file.exists():
                books.append({
                    "name": book_dir.name,
                    "display_name": book_dir.name.replace("-", " ").title(),
                    "path": f"/book/{book_dir.name}"
                })

    return sorted(books, key=lambda x: x["display_name"])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page showing list of all books"""
    books = get_books()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "books": books}
    )


@app.get("/book/{book_name}", response_class=HTMLResponse)
async def view_book(book_name: str):
    """Serve individual book view"""
    view_file = OUTPUT_DIR / book_name / "view" / "view.html"

    if not view_file.exists():
        return HTMLResponse(
            content=f"<h1>Book not found: {book_name}</h1>",
            status_code=404
        )

    return FileResponse(view_file)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "books_count": len(get_books())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3200)
