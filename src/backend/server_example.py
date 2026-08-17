from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .dependencies import get_db_manager


class User(BaseModel):
    id: int
    name: str
    email: str
    age: int


class Book(BaseModel):
    id: int
    title: str
    author: str
    year: int
    isbn: str


class PingResponse(BaseModel):
    status: str = Field(default="ok")
    message: str = Field(default="Server is running")


USERS_DATA = [
    User(id=1, name="Alice Johnson", email="alice@example.com", age=28),
    User(id=2, name="Bob Smith", email="bob@example.com", age=34),
    User(id=3, name="Charlie Brown", email="charlie@example.com", age=22),
    User(id=4, name="Diana Prince", email="diana@example.com", age=31),
]

BOOKS_DATA = [
    Book(
        id=1,
        title="The Great Gatsby",
        author="F. Scott Fitzgerald",
        year=1925,
        isbn="978-0-7432-7356-5",
    ),
    Book(
        id=2,
        title="To Kill a Mockingbird",
        author="Harper Lee",
        year=1960,
        isbn="978-0-06-112008-4",
    ),
    Book(
        id=3, title="1984", author="George Orwell", year=1949, isbn="978-0-452-28423-4"
    ),
    Book(
        id=4,
        title="Pride and Prejudice",
        author="Jane Austen",
        year=1813,
        isbn="978-0-14-143951-8",
    ),
    Book(
        id=5,
        title="The Catcher in the Rye",
        author="J.D. Salinger",
        year=1951,
        isbn="978-0-316-76948-0",
    ),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_manager = get_db_manager()
    await db_manager.initialize_tables()
    yield
    await db_manager.close()


app = FastAPI(
    title="Example FastAPI Server",
    description="A simple example server with hardcoded data",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/ping", response_model=PingResponse)
async def ping():
    return PingResponse()


@app.get("/users", response_model=List[User])
async def get_users():
    return USERS_DATA


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int):
    for user in USERS_DATA:
        if user.id == user_id:
            return user
    return User(id=0, name="Not Found", email="", age=0)


@app.get("/books", response_model=List[Book])
async def get_books():
    return BOOKS_DATA


@app.get("/books/{book_id}", response_model=Book)
async def get_book(book_id: int):
    for book in BOOKS_DATA:
        if book.id == book_id:
            return book
    return Book(id=0, title="Not Found", author="", year=0, isbn="")
