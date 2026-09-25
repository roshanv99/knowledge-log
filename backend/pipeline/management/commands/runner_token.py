"""Issue (or rotate) a runner's token. The token is printed once; only its hash is stored."""

from django.core.management.base import BaseCommand

from pipeline.models import Runner


class Command(BaseCommand):
    help = "Create a pipeline runner, or rotate its token, and print the new token."

    def add_arguments(self, parser):
        parser.add_argument("name", help='e.g. "kl@macbook"')
        parser.add_argument("--kind", choices=Runner.RunnerKind.values, default=Runner.RunnerKind.CLAUDE_SESSION)
        parser.add_argument("--disable", action="store_true", help="Revoke the runner instead.")

    def handle(self, *args, name, kind, disable, **options):
        runner = Runner.objects.filter(name=name).first()
        if disable:
            if runner:
                runner.enabled = False
                runner.save(update_fields=["enabled"])
            self.stdout.write(f"Runner {name!r} disabled." if runner else f"No runner named {name!r}.")
            return
        runner = runner or Runner(name=name, kind=kind)
        token = runner.issue_token()
        runner.kind, runner.enabled = kind, True
        runner.save()
        self.stdout.write(token)
        self.stderr.write(f"Token for {name!r}. Store it as KL_RUNNER_TOKEN (Keychain or the git-ignored .env); "
                          "it is not shown again.")
