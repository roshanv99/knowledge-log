"""Structured outputs the LLM nodes must return (validated with Pydantic)."""

from typing import Literal

from pydantic import BaseModel, Field


class KeyPoint(BaseModel):
    point: str = Field(description="One self-contained fact, including details only visible in images/tables")
    page: int = Field(description="PDF page number the fact comes from")


class ChunkNotes(BaseModel):
    title: str = Field(description="Short topic title for these pages")
    summary: str = Field(description="2-4 sentence summary of what these pages teach")
    key_points: list[KeyPoint]
    testable: bool = Field(description="False if the pages hold nothing worth quizzing (cover, index, blank)")


class MCQ(BaseModel):
    stem: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = Field(description="Why the answer is right, grounded in the notes")
    source_pages: list[int]
    difficulty: Literal["easy", "medium", "hard"]


class MCQDraft(BaseModel):
    questions: list[MCQ]


class QuestionReview(BaseModel):
    index: int = Field(description="0-based index into the draft's questions")
    verdict: Literal["approve", "revise", "reject"] = Field(
        description="approve: ship as-is. revise: correct and grounded, but has polish issues "
                    "(e.g. a weak distractor). reject: wrong, ambiguous, or not answerable from the notes.")
    issues: list[str] = Field(description="Concrete problems; empty when approved")


class Critique(BaseModel):
    reviews: list[QuestionReview]
    overall: str
