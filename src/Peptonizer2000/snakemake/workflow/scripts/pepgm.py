import argparse

from peptonizer.peptonizer import run_belief_propagation


parser = argparse.ArgumentParser(
    description="Run the PepGM algorithm from command line"
)

parser.add_argument(
    "--communities-graphml-path",
    type=str,
    required=True,
    help="Path to where the GraphML file of the factor graph (using Louvain communities) is stored.",
)
parser.add_argument(
    "--max-iter",
    nargs="?",
    type=int,
    default=10000,
    help="Max. number of iterations the belief propagation algo will go through.",
)
parser.add_argument(
    "--tol",
    nargs="?",
    type=float,
    default=0.006,
    help="Residual error allowed for the BP algorithm.",
)
parser.add_argument(
    "--out",
    type=str,
    required=True,
    help="Path to the file you want to save your results as.",
)
parser.add_argument(
    "--alpha",
    type=float,
    required=True,
    help="Detection probability of a peptide for the noisy-OR model.",
)
parser.add_argument(
    "--beta", type=float, required=True, help="Probability of wrong detection."
)
parser.add_argument(
    "--prior", type=float, required=True, help="Prior assigned to all taxa."
)
parser.add_argument(
    "--regularized",
    type=bool,
    default=False,
    help="If True, the regularized version of the noisy-OR model is used.",
)

args = parser.parse_args()

with open(args.communities_graphml_path, 'r') as in_file:
    csv_content = run_belief_propagation(
        in_file.read(),
        args.alpha,
        args.beta,
        args.regularized,
        args.prior,
        args.max_iter,
        args.tol
    )

    with open(args.out, 'w') as out_file:
        out_file.write(csv_content)
