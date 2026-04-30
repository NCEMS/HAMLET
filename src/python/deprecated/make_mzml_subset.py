#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np
from pyteomics import mzml
from psims.mzml.writer import MzMLWriter


def _get_ms_level(spec: dict) -> int | None:
    val = spec.get('ms level')
    if val is None:
        # some files may use a param object list; pyteomics usually normalizes this
        return None
    try:
        return int(val)
    except Exception:
        return None


def _get_scan_start_time(spec: dict):
    # pyteomics sometimes flattens scan start time to the top level, but some files
    # keep it nested under scanList/scan[0]. Cascadia expects the nested form.
    val = spec.get('scan start time')
    if val is None:
        try:
            scan_list = spec.get('scanList') or {}
            scans = scan_list.get('scan') or []
            if scans and isinstance(scans[0], dict):
                val = scans[0].get('scan start time')
        except Exception:
            val = None
    return val


def _build_precursor_information(spec: dict) -> dict | None:
    """Best-effort precursor information for psims.

    psims expects `precursor_information` as either:
    - a dict with keys matching `prepare_precursor_information(...)` args, or
    - a PrecursorBuilder.
    """
    precursor_list = spec.get('precursorList')
    if not precursor_list:
        return None

    precursors = precursor_list.get('precursor', [])
    if not precursors:
        return None

    precursor = precursors[0]
    selected_ions = (precursor.get('selectedIonList') or {}).get('selectedIon', [])
    selected = selected_ions[0] if selected_ions else {}
    isolation = precursor.get('isolationWindow') or {}

    info: dict = {}

    if 'selected ion m/z' in selected:
        try:
            info['mz'] = float(selected['selected ion m/z'])
        except Exception:
            pass
    if 'peak intensity' in selected:
        try:
            info['intensity'] = float(selected['peak intensity'])
        except Exception:
            pass
    if 'charge state' in selected:
        try:
            info['charge'] = int(selected['charge state'])
        except Exception:
            pass

    # Isolation window is common for DIA and can be useful.
    # psims expects keys: lower, target, upper (offsets around target).
    iso = {}
    if 'isolation window target m/z' in isolation:
        try:
            iso['target'] = float(isolation['isolation window target m/z'])
        except Exception:
            pass
    if 'isolation window lower offset' in isolation:
        try:
            iso['lower'] = float(isolation['isolation window lower offset'])
        except Exception:
            pass
    if 'isolation window upper offset' in isolation:
        try:
            iso['upper'] = float(isolation['isolation window upper offset'])
        except Exception:
            pass
    if iso:
        info['isolation_window_args'] = iso

    return info or None


def main():
    ap = argparse.ArgumentParser(description='Write a small, valid subset mzML (for testing)')
    ap.add_argument('--input', required=True, help='Input mzML path')
    ap.add_argument('--output', required=True, help='Output subset mzML path')
    ap.add_argument('--n', type=int, default=200, help='Number of spectra to keep (after filtering)')
    ap.add_argument(
        '--ms_level',
        type=int,
        default=2,
        help='Only keep spectra with this MS level. Use 0 to keep all MS levels (useful for DIA/Cascadia). Default: 2',
    )
    args = ap.parse_args()

    if args.ms_level == 0:
        args.ms_level = None

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    kept = []
    with mzml.MzML(str(in_path)) as reader:
        for spec in reader:
            ms_level = _get_ms_level(spec)
            if args.ms_level is not None and ms_level != args.ms_level:
                continue
            if 'm/z array' not in spec or 'intensity array' not in spec:
                continue
            kept.append(spec)
            if len(kept) >= args.n:
                break

    if not kept:
        raise SystemExit(f'No spectra found for ms_level={args.ms_level}')

    with open(out_path, 'wb') as fh:
        with MzMLWriter(fh) as writer:
            writer.controlled_vocabularies()
            with writer.run(id='subset_run'):
                with writer.spectrum_list(count=len(kept)):
                    for idx, spec in enumerate(kept):
                        mz_array = np.asarray(spec['m/z array'], dtype=np.float64)
                        inten_array = np.asarray(spec['intensity array'], dtype=np.float64)

                        ms_level = _get_ms_level(spec) or args.ms_level
                        scan_start_time = _get_scan_start_time(spec)
                        precursor_information = _build_precursor_information(spec)

                        params = []
                        if ms_level is not None:
                            params.append({'name': 'ms level', 'value': int(ms_level)})

                        # Use original id if present; otherwise create deterministic id
                        spectrum_id = spec.get('id') or f'scan={idx+1}'

                        kwargs = {
                            'id': spectrum_id,
                            'params': params,
                        }
                        if scan_start_time is not None:
                            kwargs['scan_start_time'] = float(scan_start_time)
                        if precursor_information is not None:
                            kwargs['precursor_information'] = precursor_information

                        writer.write_spectrum(
                            mz_array,
                            inten_array,
                            **kwargs,
                        )

    print(f'Wrote {len(kept)} spectra to {out_path}')


if __name__ == '__main__':
    main()
