import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import CrawlerError, ErrorCode
from app.models.artifacts import ArtifactDigest, RawArtifactManifest
from app.models.discovery import DiscoveredItem
from app.models.disease import DiseaseDocument
from app.models.report import FinalJobManifest, JobReport, ReportDigest
from app.models.tabs import DiseaseTabContent, RawDiseaseTab

SAFE_SLUG = re.compile(r"[^a-z0-9]+")
AUXILIARY_JSON_FILES = frozenset(
    {"disease-decision.json", "disease-draft.json", "normalization.json"}
)


class ArtifactStore:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def item_directory(
        self,
        job_id: str,
        item: DiscoveredItem,
    ) -> tuple[Path, str]:
        slug = self._slug(item.title_hint or "disease")
        relative = Path("jobs") / job_id / "items" / f"{slug}--{item.item_id[:12]}"
        return self.output_root / relative, relative.as_posix()

    def persist_import_search_audit(
        self,
        job_id: str,
        payload: dict[str, object],
    ) -> Path:
        path = self.output_root / "jobs" / job_id / "import-search.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(path, content)
        return path

    def persist_category_expansion(
        self,
        job_id: str,
        payload: dict[str, object],
    ) -> Path:
        path = self.output_root / "jobs" / job_id / "category-expansion.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(path, content)
        return path

    def read_job_json(
        self,
        job_id: str,
        file_name: str,
    ) -> dict[str, object] | None:
        try:
            payload = json.loads(
                (
                    self.output_root / "jobs" / job_id / file_name
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def persist_raw(
        self,
        *,
        job_id: str,
        plugin: str,
        item: DiscoveredItem,
        html: str,
        screenshot: bytes | None,
        confidence: float,
        tabs: tuple[RawDiseaseTab, ...] = (),
    ) -> tuple[RawArtifactManifest, str]:
        if not html.strip():
            raise CrawlerError(ErrorCode.CONTENT_EMPTY, "Raw HTML is empty")
        directory, relative = self.item_directory(job_id, item)
        directory.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, ArtifactDigest] = {}
        raw_bytes = html.encode("utf-8")
        self._atomic_write(directory / "raw.html", raw_bytes)
        artifacts["raw_html"] = self._digest("raw.html", raw_bytes)

        if tabs:
            tabs_bytes = json.dumps(
                [tab.model_dump(mode="json") for tab in tabs],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            self._atomic_write(directory / "tabs-raw.json", tabs_bytes)
            artifacts["tabs_raw"] = self._digest("tabs-raw.json", tabs_bytes)

        if screenshot is not None:
            if not screenshot.startswith(b"\x89PNG\r\n\x1a\n"):
                raise CrawlerError(
                    ErrorCode.STORAGE_WRITE,
                    "Screenshot is not a valid PNG payload",
                )
            self._atomic_write(directory / "screenshot.png", screenshot)
            artifacts["screenshot"] = self._digest("screenshot.png", screenshot)

        manifest = RawArtifactManifest(
            job_id=job_id,
            item_id=item.item_id,
            plugin=plugin,
            source_url=item.canonical_url,
            retrieved_at=datetime.now(UTC),
            confidence=confidence,
            artifacts=artifacts,
        )
        manifest_bytes = json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(directory / "manifest.json", manifest_bytes)
        return manifest, relative

    def load_valid_raw(
        self,
        job_id: str,
        item: DiscoveredItem,
    ) -> tuple[RawArtifactManifest, str] | None:
        directory, relative = self.item_directory(job_id, item)
        manifest = self._load_manifest(directory)
        if manifest is None:
            return None
        if manifest.job_id != job_id or manifest.item_id != item.item_id:
            return None
        if "raw_html" not in manifest.artifacts:
            return None
        required = ["raw_html"]
        if "tabs_raw" in manifest.artifacts:
            required.append("tabs_raw")
        if "screenshot" in manifest.artifacts:
            required.append("screenshot")
        if not self._validate_artifacts(directory, manifest, tuple(required)):
            return None
        return manifest, relative

    def persist_clean(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
        content_html: str,
        markdown: str,
        content_hash: str,
        cleaner_version: str,
        warnings: tuple[str, ...],
        snapshot_hash: str,
        snapshot_components: dict[str, str],
        previous_snapshot_hash: str | None,
        baseline_job_id: str | None,
        change_status: str,
        changed_components: tuple[str, ...],
        tabs: tuple[DiseaseTabContent, ...] = (),
    ) -> tuple[RawArtifactManifest, str]:
        current = self.load_valid_raw(job_id, item)
        if current is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "A valid raw artifact is required before cleaning",
            )
        manifest, relative = current
        directory, _ = self.item_directory(job_id, item)
        content_bytes = content_html.encode("utf-8")
        markdown_bytes = markdown.encode("utf-8")
        self._atomic_write(directory / "content.html", content_bytes)
        self._atomic_write(directory / "markdown.md", markdown_bytes)
        updated_artifacts = {
            **manifest.artifacts,
            "content_html": self._digest("content.html", content_bytes),
            "markdown": self._digest("markdown.md", markdown_bytes),
        }
        if tabs:
            tabs_bytes = json.dumps(
                [tab.model_dump(mode="json") for tab in tabs],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            self._atomic_write(directory / "tabs.json", tabs_bytes)
            updated_artifacts["tabs"] = self._digest("tabs.json", tabs_bytes)
        updated = manifest.model_copy(
            update={
                "state": "cleaned",
                "artifacts": updated_artifacts,
                "content_hash": content_hash,
                "snapshot_hash": snapshot_hash,
                "snapshot_components": snapshot_components,
                "previous_snapshot_hash": previous_snapshot_hash,
                "baseline_job_id": baseline_job_id,
                "change_status": change_status,
                "changed_components": changed_components,
                "cleaner_version": cleaner_version,
                "warnings": tuple(
                    dict.fromkeys((*manifest.warnings, *warnings))
                ),
            }
        )
        manifest_bytes = json.dumps(
            updated.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(directory / "manifest.json", manifest_bytes)
        return updated, relative

    def load_valid_clean(
        self,
        job_id: str,
        item: DiscoveredItem,
        *,
        cleaner_version: str,
    ) -> tuple[RawArtifactManifest, str] | None:
        current = self.load_valid_raw(job_id, item)
        if current is None:
            return None
        manifest, relative = current
        if (
            manifest.state not in {"cleaned", "parsed"}
            or not manifest.content_hash
            or manifest.cleaner_version != cleaner_version
            or "content_html" not in manifest.artifacts
            or "markdown" not in manifest.artifacts
        ):
            return None
        directory, _ = self.item_directory(job_id, item)
        if not self._validate_artifacts(
            directory,
            manifest,
            ("content_html", "markdown"),
        ):
            return None
        if "tabs_raw" in manifest.artifacts:
            if "tabs" not in manifest.artifacts or not self._validate_artifacts(
                directory,
                manifest,
                ("tabs",),
            ):
                return None
        try:
            markdown = (directory / "markdown.md").read_text(encoding="utf-8")
        except OSError:
            return None
        if hashlib.sha256(markdown.encode("utf-8")).hexdigest() != manifest.content_hash:
            return None
        return manifest, relative

    def persist_document(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
        document: DiseaseDocument,
        schema_hash: str,
        cleaner_version: str,
        parser_version: str,
        prompt_version: str,
        model_version: str | None,
    ) -> tuple[RawArtifactManifest, str]:
        current = self.load_valid_clean(
            job_id,
            item,
            cleaner_version=cleaner_version,
        )
        if current is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "A valid clean artifact is required before structured parsing",
            )
        manifest, relative = current
        directory, _ = self.item_directory(job_id, item)
        document_bytes = json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        DiseaseDocument.model_validate_json(document_bytes)
        self._atomic_write(directory / "disease.json", document_bytes)
        updated_artifacts = {
            **manifest.artifacts,
            "disease_json": self._digest("disease.json", document_bytes),
        }
        updated = manifest.model_copy(
            update={
                "state": "parsed",
                "artifacts": updated_artifacts,
                "schema_hash": schema_hash,
                "parser_version": parser_version,
                "prompt_version": prompt_version,
                "model_version": model_version,
                "warnings": tuple(
                    dict.fromkeys(
                        (*manifest.warnings, *document.parse_metadata.warnings)
                    )
                ),
            }
        )
        manifest_bytes = json.dumps(
            updated.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(directory / "manifest.json", manifest_bytes)
        return updated, relative

    def load_valid_document(
        self,
        job_id: str,
        item: DiscoveredItem,
        *,
        cleaner_version: str,
        parser_version: str,
        prompt_version: str,
        schema_hash: str,
        model_version: str | None,
    ) -> tuple[RawArtifactManifest, DiseaseDocument, str] | None:
        current = self.load_valid_clean(
            job_id,
            item,
            cleaner_version=cleaner_version,
        )
        if current is None:
            return None
        manifest, relative = current
        if (
            manifest.state != "parsed"
            or manifest.schema_hash != schema_hash
            or manifest.parser_version != parser_version
            or manifest.prompt_version != prompt_version
            or manifest.model_version != model_version
            or "disease_json" not in manifest.artifacts
        ):
            return None
        directory, _ = self.item_directory(job_id, item)
        if not self._validate_artifacts(
            directory,
            manifest,
            ("disease_json",),
        ):
            return None
        try:
            document = DiseaseDocument.model_validate_json(
                (directory / "disease.json").read_bytes()
            )
        except (OSError, ValueError):
            return None
        if document.source.content_hash != manifest.content_hash:
            return None
        return manifest, document, relative

    def reuse_valid_document(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
        baseline_job_id: str,
        baseline_item: DiscoveredItem,
        cleaner_version: str,
        parser_version: str,
        prompt_version: str,
        schema_hash: str,
        model_version: str | None,
    ) -> tuple[RawArtifactManifest, DiseaseDocument, str] | None:
        current = self.load_valid_clean(
            job_id,
            item,
            cleaner_version=cleaner_version,
        )
        if current is None:
            return None
        current_manifest, _ = current
        if (
            current_manifest.change_status != "unchanged"
            or current_manifest.baseline_job_id != baseline_job_id
        ):
            return None
        baseline = self.load_valid_document(
            baseline_job_id,
            baseline_item,
            cleaner_version=cleaner_version,
            parser_version=parser_version,
            prompt_version=prompt_version,
            schema_hash=schema_hash,
            model_version=model_version,
        )
        if baseline is None:
            return None
        _, baseline_document, _ = baseline
        source = baseline_document.source.model_copy(
            update={
                "url": item.source_url,
                "canonical_url": item.canonical_url,
                "retrieved_at": current_manifest.retrieved_at,
                "content_hash": current_manifest.content_hash,
            }
        )
        metadata = baseline_document.parse_metadata.model_copy(
            update={
                "warnings": tuple(
                    dict.fromkeys(
                        (
                            *baseline_document.parse_metadata.warnings,
                            "incremental_unchanged_reused",
                        )
                    )
                )
            }
        )
        document = baseline_document.model_copy(
            update={
                "source": source,
                "tabs": self.read_tabs(
                    job_id,
                    item,
                    cleaner_version=cleaner_version,
                ),
                "parse_metadata": metadata,
            }
        )
        manifest, relative = self.persist_document(
            job_id=job_id,
            item=item,
            document=document,
            schema_hash=schema_hash,
            cleaner_version=cleaner_version,
            parser_version=parser_version,
            prompt_version=prompt_version,
            model_version=model_version,
        )
        return manifest, document, relative

    def read_raw_html(self, job_id: str, item: DiscoveredItem) -> str:
        current = self.load_valid_raw(job_id, item)
        if current is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Raw artifact is missing or failed checksum validation",
            )
        directory, _ = self.item_directory(job_id, item)
        try:
            return (directory / "raw.html").read_text(encoding="utf-8")
        except OSError as exc:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Raw HTML could not be read",
            ) from exc

    def read_raw_tabs(
        self,
        job_id: str,
        item: DiscoveredItem,
    ) -> tuple[RawDiseaseTab, ...]:
        current = self.load_valid_raw(job_id, item)
        if current is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Raw artifact is missing or failed checksum validation",
            )
        manifest, _ = current
        artifact = manifest.artifacts.get("tabs_raw")
        if artifact is None:
            return ()
        directory, _ = self.item_directory(job_id, item)
        try:
            payload = json.loads(
                (directory / artifact.name).read_text(encoding="utf-8")
            )
            return tuple(RawDiseaseTab.model_validate(tab) for tab in payload)
        except (OSError, TypeError, ValueError) as exc:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Raw tab artifact could not be read",
            ) from exc

    def read_markdown(
        self,
        job_id: str,
        item: DiscoveredItem,
        *,
        cleaner_version: str,
    ) -> tuple[RawArtifactManifest, str]:
        current = self.load_valid_clean(
            job_id,
            item,
            cleaner_version=cleaner_version,
        )
        if current is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Clean Markdown artifact is missing or failed validation",
            )
        manifest, _ = current
        directory, _ = self.item_directory(job_id, item)
        try:
            return manifest, (directory / "markdown.md").read_text(encoding="utf-8")
        except OSError as exc:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Markdown artifact could not be read",
            ) from exc

    def read_tabs(
        self,
        job_id: str,
        item: DiscoveredItem,
        *,
        cleaner_version: str,
    ) -> tuple[DiseaseTabContent, ...]:
        current = self.load_valid_clean(
            job_id,
            item,
            cleaner_version=cleaner_version,
        )
        if current is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Clean tab artifact is missing or failed validation",
            )
        manifest, _ = current
        artifact = manifest.artifacts.get("tabs")
        if artifact is None:
            return ()
        directory, _ = self.item_directory(job_id, item)
        try:
            payload = json.loads(
                (directory / artifact.name).read_text(encoding="utf-8")
            )
            return tuple(
                DiseaseTabContent.model_validate(tab) for tab in payload
            )
        except (OSError, TypeError, ValueError) as exc:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Clean tab artifact could not be read",
            ) from exc

    def persist_auxiliary_json(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
        file_name: str,
        payload: object,
    ) -> None:
        if file_name not in AUXILIARY_JSON_FILES:
            raise ValueError("Unsupported auxiliary artifact name")
        manifest = self.load_item_manifest(job_id, item)
        if manifest is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "A valid item manifest is required for agent artifacts",
            )
        directory, _ = self.item_directory(job_id, item)
        payload_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(directory / file_name, payload_bytes)
        updated = manifest.model_copy(
            update={
                "artifacts": {
                    **manifest.artifacts,
                    file_name.removesuffix(".json").replace("-", "_"): (
                        self._digest(file_name, payload_bytes)
                    ),
                }
            }
        )
        self._atomic_write(
            directory / "manifest.json",
            json.dumps(
                updated.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
        )

    def load_item_manifest(
        self,
        job_id: str,
        item: DiscoveredItem,
    ) -> RawArtifactManifest | None:
        directory, _ = self.item_directory(job_id, item)
        manifest = self._load_manifest(directory)
        if (
            manifest is None
            or manifest.job_id != job_id
            or manifest.item_id != item.item_id
        ):
            return None
        return manifest

    def persist_job_report(self, report: JobReport) -> FinalJobManifest:
        directory = self.output_root / "jobs" / report.job_id
        directory.mkdir(parents=True, exist_ok=True)
        report_bytes = json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        JobReport.model_validate_json(report_bytes)
        self._atomic_write(directory / "report.json", report_bytes)
        final = FinalJobManifest(
            job_id=report.job_id,
            plugin=report.plugin,
            status=report.status,
            report=ReportDigest.model_validate(
                self._digest("report.json", report_bytes).model_dump()
            ),
            item_count=report.total_items,
            successful_items=report.successful_items,
            failed_items=report.failed_items,
        )
        manifest_bytes = json.dumps(
            final.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        FinalJobManifest.model_validate_json(manifest_bytes)
        self._atomic_write(directory / "job.json", manifest_bytes)
        return final

    def load_job_report(self, job_id: str) -> JobReport | None:
        path = self.output_root / "jobs" / job_id / "report.json"
        try:
            return JobReport.model_validate_json(path.read_bytes())
        except (OSError, ValueError):
            return None

    def has_job_report(self, job_id: str) -> bool:
        return self.load_job_report(job_id) is not None

    def _atomic_write(self, target: Path, payload: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, target)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise CrawlerError(
                ErrorCode.STORAGE_WRITE,
                f"Could not atomically persist {target.name}",
            ) from exc

    def _slug(self, value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value).encode(
            "ascii", "ignore"
        ).decode()
        slug = SAFE_SLUG.sub("-", ascii_value.lower()).strip("-")
        return (slug or "disease")[:60].rstrip("-")

    def _digest(self, name: str, payload: bytes) -> ArtifactDigest:
        return ArtifactDigest(
            name=name,
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def _load_manifest(self, directory: Path) -> RawArtifactManifest | None:
        try:
            return RawArtifactManifest.model_validate_json(
                (directory / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _validate_artifacts(
        self,
        directory: Path,
        manifest: RawArtifactManifest,
        keys: tuple[str, ...],
    ) -> bool:
        for key in keys:
            artifact = manifest.artifacts.get(key)
            if artifact is None:
                return False
            try:
                payload = (directory / artifact.name).read_bytes()
            except OSError:
                return False
            if len(payload) != artifact.size:
                return False
            if hashlib.sha256(payload).hexdigest() != artifact.sha256:
                return False
        return True
