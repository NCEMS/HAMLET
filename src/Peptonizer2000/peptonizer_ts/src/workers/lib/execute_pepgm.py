import json
import peptonizer
# Provided by Pyodide, required to send status updates from this thread to the main thread in JavaScript.
import js


class JSZeroLookaheadProgressListener(peptonizer.ZeroLookaheadProgressListener):
    def __init__(self, execution_id: int):
        self.execution_id = execution_id

    def graphs_updated(
        self,
        current_graph: int,
        total_graphs: int
    ):
        js.submitPepgmProgress("graph", current_graph, total_graphs, self.execution_id)

    def max_residual_updated(
        self,
        max_residual: float,
        tolerance: float,
    ):
        js.submitPepgmProgress("max_residual", max_residual, tolerance, self.execution_id)

    def iterations_updated(
        self,
        current_iterations: int,
        total_iterations: int
    ):
        js.submitPepgmProgress("iteration", current_iterations, total_iterations, self.execution_id)

graph = globals().get('graph')
alpha = globals().get('alpha')
beta = globals().get('beta')
prior = globals().get('prior')
execution_id = globals().get('worker_id')

pepgm_results = peptonizer.run_belief_propagation(
    graph,
    alpha,
    beta,
    True,
    prior,
    progress_listener=JSZeroLookaheadProgressListener(execution_id)
)

# Now convert the results from PepGM into a list of taxon IDs and the corresponding score values.
json.dumps(peptonizer.parse_taxon_scores(pepgm_results))
