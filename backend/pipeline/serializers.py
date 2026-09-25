"""What runners may send. The step engine validates first; the server checks again here."""

import json

from rest_framework import serializers

from content.models import Kind

MAX_JSON_BYTES = 256 * 1024


def _small_json(value):
    if len(json.dumps(value)) > MAX_JSON_BYTES:
        raise serializers.ValidationError(f"Too large (over {MAX_JSON_BYTES // 1024} KB).")
    return value


class StartRunInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Kind.choices)
    params = serializers.DictField(required=False, default=dict, validators=[_small_json])


class ClaimInput(serializers.Serializer):
    document_id = serializers.IntegerField(required=False, allow_null=True)


class RunCallInput(serializers.Serializer):
    run_id = serializers.IntegerField()


class HeartbeatInput(RunCallInput):
    stage = serializers.CharField(max_length=32)
    detail = serializers.CharField(max_length=500, required=False, allow_null=True, allow_blank=True)


class KeyPointInput(serializers.Serializer):
    point = serializers.CharField(max_length=2000)
    page = serializers.IntegerField(min_value=1)


class NotesInput(RunCallInput):
    title = serializers.CharField(max_length=300)
    summary = serializers.CharField(max_length=4000, allow_blank=True)
    key_points = KeyPointInput(many=True, max_length=200)
    testable = serializers.BooleanField()


class QuestionInput(serializers.Serializer):
    stem = serializers.CharField(max_length=2000)
    options = serializers.ListField(child=serializers.CharField(max_length=500), min_length=4, max_length=4)
    correct_index = serializers.IntegerField(min_value=0, max_value=3)
    explanation = serializers.CharField(max_length=4000)
    source_pages = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=20)
    difficulty = serializers.ChoiceField(choices=["easy", "medium", "hard"])

    def validate_options(self, value):
        if len({o.strip().lower() for o in value}) != len(value):
            raise serializers.ValidationError("Options must be distinct.")
        return value


class ReelInput(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    key_point = serializers.CharField(max_length=500, required=False, allow_blank=True)
    duration_s = serializers.FloatField(min_value=1, max_value=600, required=False, allow_null=True)
    storage_key = serializers.RegexField(r"^reels/task-\d+\.mp4$", max_length=64)


class CompleteInput(RunCallInput):
    questions = QuestionInput(many=True, max_length=20, required=False, default=list)
    reel = ReelInput(required=False, allow_null=True, default=None)
    review_log = serializers.ListField(required=False, default=list, validators=[_small_json])
    skipped_reason = serializers.CharField(max_length=500, required=False, allow_null=True)

    def validate(self, data):
        pages = self.context["pages"]
        for i, q in enumerate(data["questions"]):
            outside = sorted(set(q["source_pages"]) - pages)
            if outside:
                raise serializers.ValidationError(
                    {"questions": f"Question {i} cites pages {outside}, outside this chunk "
                                  f"({min(pages)}-{max(pages)})."})
        stems = [q["stem"].strip() for q in data["questions"]]
        if len(set(stems)) != len(stems):
            raise serializers.ValidationError({"questions": "Two questions share a stem."})
        return data


class FailInput(RunCallInput):
    error = serializers.CharField(max_length=4000)
    retryable = serializers.BooleanField(default=True)


class FinishInput(serializers.Serializer):
    stop_reason = serializers.CharField(max_length=32)
    usage = serializers.DictField(required=False, allow_null=True, default=None)


class RequestInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Kind.choices)


class NotesSyncEntryInput(serializers.Serializer):
    path = serializers.CharField(max_length=2000)
    filename = serializers.CharField(max_length=512)
    file_hash = serializers.CharField(max_length=64)
    size = serializers.IntegerField(min_value=0)
    mtime = serializers.FloatField()
    page_count = serializers.IntegerField(min_value=1)
    folder = serializers.CharField(max_length=500, allow_blank=True)


class NotesSyncInput(serializers.Serializer):
    notes_dir = serializers.CharField(max_length=500, allow_blank=True)
    documents = NotesSyncEntryInput(many=True, max_length=2000)
