"""Export exact report originals to temporary files for host attachment admission."""
import json
import sys
from pathlib import Path

from insight.adapters.export.narrative import render_pdf_page
from insight.bootstrap import Application
from insight.domain.contracts import PlatformError, ReportFigure


def export_figures(app, run_id, directory):
    """Read current figure artifacts without modifying research records."""
    with app.queries.tx(None) as repo:
        analysis = repo.analysis(run_id)
        context = repo.context(run_id)
        versions = {v.version_id: v for v in repo.versions(run_id)}
        figures = [b for s in analysis.narrative.sections for b in s.blocks
                   if isinstance(b, ReportFigure)] if analysis and analysis.narrative else []
        references = {(figure.source_version_id, figure.unit_index, figure.image_artifact_id)
                      for figure in figures}
        if context:
            references.update((e.source_version_id, e.locator.unit_index, None)
                              for e in context.evidence
                              if getattr(e.locator, 'modality', None) == 'visual_page')
        originals = []
        for version, unit, image_id in sorted(references, key=lambda item: (item[0], item[1], item[2] or '')):
            artifact = repo.artifact(image_id or versions[version].raw_artifact_id)
            originals.append((version, unit, image_id, artifact))
    result = []
    for index, (version, unit, image_id, artifact) in enumerate(originals):
        data = app.blobs.read(artifact)
        if image_id:
            media_type = artifact.media_type
            suffix = '.png' if media_type == 'image/png' else '.jpg'
        else:
            data = render_pdf_page(data, unit, directory)
            media_type, suffix = 'image/png', '.png'
        path = directory / (str(index) + suffix)
        path.write_bytes(data)
        result.append({'path': str(path), 'mediaType': media_type,
                       'source_version_id': version,
                       'unit_index': unit})
    return result


if __name__ == '__main__':
    app = Application(Path(sys.argv[1]))
    try:
        print(json.dumps(export_figures(app, sys.argv[2], Path(sys.argv[3]))))
    except PlatformError as error:
        print(json.dumps({'error': {'code': error.code, 'detail': str(error)}}))
        sys.exit(1)
    finally:
        app.close()
