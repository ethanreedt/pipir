"""pipir command-line interface.

    pipir input.slp                     # IR to stdout
    pipir input.slp -o out.pipir        # IR to file
    pipir --from slp input.slp          # explicit input dialect (default: slp)
"""

import argparse
import json
import os
import sys

from . import __version__
from .convert import convert_slp
from .parse_slp import SlpError

DIALECTS = ("slp",)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pipir",
        description="Convert an ETL platform pipeline export to ETL-IR (.pipir).",
    )
    parser.add_argument("input", help="pipeline export file (.slp)")
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="write IR here instead of stdout")
    parser.add_argument("--from", dest="input_type", choices=DIALECTS,
                        default="slp",
                        help="input dialect (default: %(default)s)")
    parser.add_argument("--coverage", action="store_true",
                        help="print a typed/classified/opaque snap coverage "
                             "report instead of IR")
    parser.add_argument("--version", action="version",
                        version="pipir %s (etl-ir 0.1)" % __version__)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except OSError as exc:
        print("pipir: cannot read %s: %s" % (args.input, exc.strerror or exc),
              file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print("pipir: %s is not valid JSON: %s" % (args.input, exc),
              file=sys.stderr)
        return 2

    stem = os.path.splitext(os.path.basename(args.input))[0]
    try:
        if args.coverage:
            from .report import coverage, format_coverage
            text = format_coverage(coverage(doc))
        else:
            text = convert_slp(doc, name_fallback=stem)
    except SlpError as exc:
        print("pipir: %s: %s" % (args.input, exc), file=sys.stderr)
        return 2

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
