"""
CLI Main Entry Point

Provides the `envelope` command with subcommands:
- validate: Validate a manifest
- deploy: Deploy a model with envelope
- verify: Run verification tests
- replay: Replay a historical request
"""

import sys
from pathlib import Path

import click


@click.group()
@click.version_option(version="0.1.0", prog_name="envelope")
def cli():
    """Model Deployment Envelope CLI.

    Platform-enforced boundaries for AI model deployments.
    """
    pass


@cli.command()
@click.argument("manifest_path", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
def validate(manifest_path: str, strict: bool):
    """Validate a model manifest.

    Performs structural validation against JSON schema and
    checks references to tools, data classes, and placement policies.
    """
    from envelope.declaration.manifest import ManifestLoader
    from envelope.validation.structural import StructuralValidator

    path = Path(manifest_path)
    click.echo(f"Validating manifest: {path}")

    try:
        loader = ManifestLoader()
        manifest = loader.load(path)
        click.echo(f"  Schema validation: PASSED")

        validator = StructuralValidator()
        result = validator.validate(manifest)

        if result.errors:
            click.echo(f"  Structural validation: FAILED")
            for error in result.errors:
                click.echo(f"    ERROR: {error}", err=True)
            sys.exit(1)

        if result.warnings:
            click.echo(f"  Warnings:")
            for warning in result.warnings:
                click.echo(f"    WARNING: {warning}")

            if strict:
                click.echo("  Strict mode: treating warnings as errors")
                sys.exit(1)

        click.echo(f"  Structural validation: PASSED")
        click.echo(f"\nManifest: {manifest.metadata.name} v{manifest.metadata.version}")
        click.echo(f"Model: {manifest.model_id} ({manifest.backend})")
        click.echo(f"Tools: {len(manifest.spec.tools.allowed)}")
        click.echo(f"Data classes: {len(manifest.spec.data_classes.allowed)}")

    except Exception as e:
        click.echo(f"Validation failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("manifest_path", type=click.Path(exists=True))
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def deploy(manifest_path: str, host: str, port: int, reload: bool):
    """Deploy a model with envelope enforcement.

    Starts the FastAPI server with the specified manifest.
    """
    import uvicorn

    from envelope.declaration.manifest import ManifestLoader
    from envelope.runtime.adapters.base import AdapterConfig, create_adapter
    from envelope.api.main import create_app

    path = Path(manifest_path)
    click.echo(f"Loading manifest: {path}")

    try:
        loader = ManifestLoader()
        manifest = loader.load(path)

        click.echo(f"Creating runtime adapter: {manifest.backend}")
        config = AdapterConfig(
            backend=manifest.backend,
            model_id=manifest.model_id,
            endpoint=manifest.spec.model.endpoint,
        )

        try:
            runtime = create_adapter(config)
        except Exception as e:
            click.echo(f"Warning: Could not create runtime adapter: {e}")
            click.echo("Starting without runtime (demo mode)")
            runtime = None

        click.echo(f"Creating application...")
        app = create_app(manifest=manifest, runtime=runtime)

        click.echo(f"\nStarting server on {host}:{port}")
        click.echo(f"Manifest: {manifest.metadata.name} v{manifest.metadata.version}")
        click.echo(f"Model: {manifest.model_id}")
        click.echo(f"Press Ctrl+C to stop\n")

        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=reload,
        )

    except Exception as e:
        click.echo(f"Deployment failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--target", default="http://localhost:8000", help="Target URL")
@click.option("--category", multiple=True, help="Test categories to run")
@click.option("--tag", multiple=True, help="Test tags to filter")
@click.option("--output", type=click.Path(), help="Output file for report")
@click.option("--format", type=click.Choice(["text", "json", "html"]), default="text")
def verify(target: str, category: tuple, tag: tuple, output: str | None, format: str):
    """Run verification tests against a deployed envelope.

    Executes conformance and golden set tests.
    """
    import asyncio
    import httpx

    async def run_verification():
        click.echo(f"Running verification against: {target}")

        async with httpx.AsyncClient(base_url=target, timeout=60.0) as client:
            # Check health
            try:
                response = await client.get("/health")
                if response.status_code != 200:
                    click.echo(f"Target is not healthy: {response.status_code}", err=True)
                    return 1
            except Exception as e:
                click.echo(f"Cannot connect to target: {e}", err=True)
                return 1

            click.echo("Target is healthy")

            # Run conformance tests
            params = {}
            if category:
                params["categories"] = list(category)
            if tag:
                params["tags"] = list(tag)

            click.echo("\nRunning conformance tests...")
            try:
                response = await client.post("/verify/conformance/run", params=params)
                result = response.json()

                click.echo(f"  Passed: {result['passed']}")
                click.echo(f"  Failed: {result['failed']}")
                click.echo(f"  Pass rate: {result['pass_rate']:.1%}")

                if result['failed'] > 0:
                    click.echo("\n  Failed tests:")
                    for exec in result['executions']:
                        if exec['result'] != 'passed':
                            click.echo(f"    - {exec['test_id']}: {exec['message']}")

            except Exception as e:
                click.echo(f"  Error running tests: {e}", err=True)

            # Get report
            if output:
                click.echo(f"\nGenerating report...")
                response = await client.get(f"/verify/report?format={format}")

                Path(output).write_text(response.text)
                click.echo(f"Report saved to: {output}")

        return 0 if result.get('success', False) else 1

    exit_code = asyncio.run(run_verification())
    sys.exit(exit_code)


@cli.command()
@click.argument("request_id")
@click.option("--target", default="http://localhost:8000", help="Target URL")
def replay(request_id: str, target: str):
    """Replay a historical request for debugging.

    Fetches the original request from provenance and re-executes it.
    """
    import asyncio
    import httpx

    async def run_replay():
        click.echo(f"Replaying request: {request_id}")

        async with httpx.AsyncClient(base_url=target, timeout=60.0) as client:
            try:
                response = await client.get(f"/verify/replay/{request_id}")

                if response.status_code == 404:
                    click.echo(f"Request not found: {request_id}", err=True)
                    return 1

                if response.status_code != 200:
                    click.echo(f"Replay failed: {response.text}", err=True)
                    return 1

                result = response.json()

                click.echo(f"\nReplay Results:")
                click.echo(f"  Exact match: {'Yes' if result['exact_match'] else 'No'}")
                click.echo(f"  Similarity: {result['similarity_score']:.1%}")
                click.echo(f"  Duration: {result['duration_ms']:.1f}ms")

                if result['differences']:
                    click.echo(f"\n  Differences:")
                    for diff in result['differences']:
                        click.echo(f"    - {diff}")

                return 0 if result['exact_match'] else 1

            except Exception as e:
                click.echo(f"Replay failed: {e}", err=True)
                return 1

    exit_code = asyncio.run(run_replay())
    sys.exit(exit_code)


@cli.command()
@click.option("--output", type=click.Path(), required=True, help="Output file")
@click.option("--format", type=click.Choice(["html", "json", "md"]), default="html")
@click.option("--target", default="http://localhost:8000", help="Target URL")
def report(output: str, format: str, target: str):
    """Generate a conformance report.

    Creates an HTML, JSON, or Markdown report from test results.
    """
    import asyncio
    import httpx

    async def generate_report():
        click.echo(f"Generating {format} report...")

        async with httpx.AsyncClient(base_url=target, timeout=60.0) as client:
            try:
                response = await client.get(f"/verify/report?format={format}")

                if response.status_code != 200:
                    click.echo(f"Failed to generate report: {response.text}", err=True)
                    return 1

                Path(output).write_text(response.text)
                click.echo(f"Report saved to: {output}")
                return 0

            except Exception as e:
                click.echo(f"Report generation failed: {e}", err=True)
                return 1

    exit_code = asyncio.run(generate_report())
    sys.exit(exit_code)


if __name__ == "__main__":
    cli()
