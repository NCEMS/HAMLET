# implementation of belief propagation on a peptide-protein graph
# __________________________________________________________________________________________
from enum import Enum
from sys import getsizeof

from .convolution_tree import *
from .factor_graph_generation import *
from .pqdict import pqdict
from typing import Dict, Any, List, Tuple, Iterator


class ZeroLookaheadProgressListener:
    def graphs_updated(
        self,
        current_graph: int,
        total_graphs: int
    ):
        """
        Called when the belief propagation algorithm is started on a new subgraph.

        Parameters
        ----------
        current_graph: int
            Which subgraph in the whole factor graph the belief propagation algorithm is started for.
        total_graphs: int
            The total amount of subgraphs (or communities) that are present in the whole factor graph.
        """
        pass

    def max_residual_updated(
        self,
        max_residual: float,
        tolerance: float
    ):
        """
        Called when a new, better max_residual score has been found by the belief propagation algorithm.

        Parameters
        ----------
        max_residual: float
            The new max_residual score that has been found (will thus be lower than the previous one)
        tolerance: float
            The minimum residual score required for the convergence of the belief propagation algorithm to be considered
            complete.
        """
        pass

    def iterations_updated(
        self,
        current_iteration: int,
        total_iterations: int,
    ):
        """
        Called everytime the belief propagation algorithm has finished processing one or more complete iterations of the
        message loop.

        Parameters
        ----------
        current_iteration: int
            The current iteration for which execution has just completed.
        total_iterations: int
            The maximum amount of iterations that will be performed before the belief propagation algorithm is stopped.
            Note that the algorithm can be stopped earlier if convergence has already been achieved.
        """
        pass


class PrintZeroLookaheadProgressListener(ZeroLookaheadProgressListener):
    def graphs_updated(
            self,
            current_graph: int,
            total_graphs: int
    ):
        print(f"Finished calibration of {current_graph} of {total_graphs}")

    def max_residual_updated(
            self,
            max_residual: float,
            tolerance: float
    ):
        print(f"Improved maximum residual to {max_residual}. Convergence is met when lower than {tolerance}.")

    def iterations_updated(
            self,
            current_iteration: int,
            total_iterations: int,
    ):
        print(f"Finished message loop iteration {current_iteration} / {total_iterations}.")


class Category(Enum):
    peptide = 0
    factor = 1
    convolution_tree = 2
    taxon = 3


class Messages:
    """
    Class holding all messages and beliefs.
    Functions execute loopy residual belief propagation with zero look ahead
    """

    # class that holds the messages of iteration t and iteration t+1 as dictionaries
    def __init__(self, ct_graph_in: CTFactorGraph):
        self.max_val: Optional[Tuple[int, int]] = None
        self.priorities: pqdict = pqdict({}, reverse=True)
        self.category: Category = Category[ct_graph_in.category]

        amount_of_nodes = ct_graph_in.number_of_nodes()

        # Maps a node identifier (as specified by the CTGraph) onto a unique integer.
        self.node_descriptions: Dict[str, int] = {}
        # Reverse mapping of the dict above
        self.node_id_to_description: List[str] = []
        # Maps a node ID onto its category
        self.categories: List[Category] = []
        # Maps a node ID onto a list of its neighbouring node IDs
        self.neighbours: List[List[int]] = []
        # Keeps track of the number of parents of a node
        self.number_of_parents: List[int] = [0 for _ in range(amount_of_nodes)]
        # Maps an edge as a tuple of node ids to an id
        self.edge_ids: Dict[Tuple[int, int], int] = {}
        # Reverse mapping of the dict above
        self.edges: List[Tuple[int, int]] = []

        # Keeps track of residuals for duos of edges, indexed by [edge index][neighbour index of edge's end node]
        self.total_residuals: List[List[float]] = []

        # Maps a node ID onto its initial belief value
        self.initial_beliefs: List[npt.NDArray[np.float64]] = []
        # Maps a node ID onto its current belief value
        self.current_beliefs: List[npt.NDArray[np.float64]] = []

        # Incoming messages for each node
        self.msg_in: List[List[npt.NDArray[np.float64]]] = []
        self.msg_in_new: List[List[npt.NDArray[np.float64]]] = []
        self.msg_in_log: List[List[npt.NDArray[np.float64]]] = []

        nodes: Iterator[Tuple[Any, Dict[str, Any]]] = ct_graph_in.nodes(data=True)

        for (node_id, node) in enumerate(nodes):
            # Each node should occur exactly once
            assert node[0] not in self.node_descriptions

            self.node_descriptions[node[0]] = node_id
            self.node_id_to_description.append(node[0])
            self.categories.append(Category[node[1]["category"]])

            # Only convolution trees have a number of parents property assigned to them.
            if node[1]["category"] == "convolution_tree":
                self.number_of_parents[node_id] = node[1]["NumberOfParents"]

            if node[1]["category"] == "factor":
                self.initial_beliefs.append(node[1]["InitialBelief"].factor.array)
            elif node[1]["category"] == "peptide" or node[1]["category"] == ct_graph_in.category:
                self.initial_beliefs.append(np.array([node[1]["InitialBelief_0"], node[1]["InitialBelief_1"]]))
            else:
                # this entry will never be used as the convolution trees do not hold beliefs
                self.initial_beliefs.append(np.ones(4))

        # We start out with current beliefs that are identical to the initial beliefs
        self.current_beliefs = self.initial_beliefs.copy()

        # Now that all nodes have been processed, we need to replace all the neighbours of a node by their node IDs
        for (node_id, node) in enumerate(ct_graph_in.nodes(data=True)):
            self.neighbours.append([self.node_descriptions[n] for n in ct_graph_in.neighbors(node[0])])

        # Incoming messages for each node, initialize with correct dimensions
        self.msg_in = [[np.zeros(0) for _ in range(len(self.neighbours[i]))] for i in range(amount_of_nodes)]
        self.msg_in_new = [[np.zeros(0) for _ in range(len(self.neighbours[i]))] for i in range(amount_of_nodes)]
        self.msg_in_log = [[np.zeros(0) for _ in range(len(self.neighbours[i]))] for i in range(amount_of_nodes)]

        # Now, also replace the edge descriptions by the corresponding node IDs
        edge_id: int = 0
        for start_node, end_node, data in ct_graph_in.edges(data=True):
            start_node_id = self.node_descriptions[start_node]
            end_node_id = self.node_descriptions[end_node]

            rev_edge_id = edge_id + 1
            self.edge_ids[(start_node_id, end_node_id)] = edge_id
            self.edges.append((start_node_id, end_node_id))
            self.edge_ids[(end_node_id, start_node_id)] = rev_edge_id
            self.edges.append((end_node_id, start_node_id))

            start_neighbour_index: int = self.neighbours[end_node_id].index(start_node_id)
            if "MessageLength" in data:
                self.msg_in[end_node_id][start_neighbour_index] = np.ones(data["MessageLength"])
                self.msg_in_new[end_node_id][start_neighbour_index] = np.ones(data["MessageLength"])
            else:
                self.msg_in[end_node_id][start_neighbour_index] = np.array([0.5, 0.5])
                self.msg_in_new[end_node_id][start_neighbour_index] = np.array([0, 0])

            end_neighbour_index = self.neighbours[start_node_id].index(end_node_id)
            self.msg_in[start_node_id][end_neighbour_index] = self.msg_in[end_node_id][start_neighbour_index]
            self.msg_in_new[start_node_id][end_neighbour_index] = self.msg_in_new[end_node_id][start_neighbour_index]

            edge_id += 2

        self.total_residuals = [[0 for _ in self.neighbours[end_node]] for (_, end_node) in self.edges]
        self.msg_in_log = [msg_in.copy() for msg_in in self.msg_in_new]


    def print_mem_usage(self):
        print("max_val: " + str(getsizeof(self.max_val)) + " bytes")
        priorities_size = len(self.priorities) * (2 * getsizeof(int()))
        print("priorities (app): " + str(priorities_size) + " bytes")
        print("category: " + str(getsizeof(self.category)) + " bytes")

        node_descriptions = len(self.node_descriptions) * (getsizeof(int()) + getsizeof("factor"))
        print("node_descriptions: " + str(node_descriptions) + " bytes")
        node_id_to_description = len(self.node_id_to_description) * (getsizeof("factor"))
        print("node_id_to_description: " + str(node_id_to_description) + " bytes")

        categories = len(self.categories) * (getsizeof(Category))
        print("categories: " + str(categories) + " bytes")

        total_neighbours = sum([len(n) for n in self.neighbours])
        neighbours = total_neighbours * getsizeof(int()) + len(self.neighbours) * (getsizeof([]))
        print("neighbours: " + str(neighbours) + " bytes")

        number_of_parents = len(self.number_of_parents) * (getsizeof(int()))
        print("number_of_parents: " + str(number_of_parents) + " bytes")

        edge_ids = len(self.edge_ids) * (getsizeof((int(), int())) + getsizeof(int()))
        print("edge_ids: " + str(edge_ids) + " bytes")
        edges = len(self.edges) * getsizeof((int(), int()))
        print("edges: " + str(edges) + " bytes")

        total_edge_duos = sum([len(self.neighbours[end_node]) for (_, end_node) in self.edges])
        total_residuals = total_edge_duos * getsizeof(float()) + len(self.total_residuals) * getsizeof([])
        print("total_residuals: " + str(total_residuals) + " bytes")

        total_belief_size = sum([len(n) for n in self.initial_beliefs])
        initial_beliefs = len(self.initial_beliefs) * getsizeof(np.array([])) + total_belief_size * 8
        print("initial_beliefs / current_beliefs: " + str(initial_beliefs) + " bytes")

        # Incoming messages for each node
        total_msg_length = sum([sum([len(m) for m in n]) for n in self.msg_in])
        total_msg_lists = sum([len(n) for n in self.msg_in]) + len(self.msg_in)
        msg_in = total_msg_length * 8 + total_msg_lists * getsizeof([])
        print("msg_in / msg_in_new / msg_in_log: " + str(msg_in) + " bytes")

    def compute_out_message_variable(self, node_out: int, node_in: int) -> npt.NDArray[np.float64]:
        node_in_neighbour_index = self.neighbours[node_out].index(node_in)
        incoming_messages: List[npt.NDArray[np.float64]] = self.msg_in[node_out].copy()
        incoming_messages.pop(node_in_neighbour_index)
        node_belief: npt.NDArray[np.float64] = self.current_beliefs[node_out]

        if not incoming_messages:
            node_out_neighbour_id = self.neighbours[node_in].index(node_out)
            return node_belief if any(node_belief == self.initial_beliefs[node_out]) else self.msg_in[node_in][node_out_neighbour_id]

        # need for logs to prevent underflow in very large multiplications
        incoming_messages_array = np.asarray(np.log(incoming_messages)).reshape(
            len(incoming_messages), 2
        )

        out_message_log = array_utils.log_normalize(
            np.log(node_belief) + np.sum(incoming_messages_array, axis=0)
        )

        if not np.all(out_message_log):
            out_message_log[out_message_log == 0] = 1e-30

        return out_message_log

    def compute_out_message_factor(self, node_out: int, node_in: int) -> npt.NDArray[np.float64]:
        node_in_neighbour_index = self.neighbours[node_out].index(node_in)
        incoming_messages: List[npt.NDArray[np.float64]] = self.msg_in[node_out].copy()
        incoming_messages.pop(node_in_neighbour_index)
        node_belief = self.current_beliefs[node_out]

        if self.categories[node_in] == Category.convolution_tree:
            # handles empty & messages with only one value
            incoming_messages.append(np.asarray([1.0, 1.0]))
            in_messages_array: npt.NDArray[np.float64] = np.asarray(incoming_messages).reshape(
                len(incoming_messages), 2
            )
            out_messages = array_utils.normalize(
                np.multiply(node_belief, np.prod(in_messages_array, axis=0))
            )  # lognormalize(np.add(np.log(NodeBelief),[np.sum(IncomingMessages[:,0]),np.sum(IncomingMessages[:,1])]))#

            return np.sum(out_messages, axis=1)
        else:
            if len(incoming_messages[0]) > 2:
                incoming_messages_log = np.log(
                    np.asarray(incoming_messages).reshape(
                        len(incoming_messages[0]), 1
                    )
                )
                # catch warning for log(0)

                log_belief = np.log(node_belief)
                out_messages_log = array_utils.log_normalize(log_belief + incoming_messages_log)
                if not np.all(out_messages_log):
                    out_messages_log[out_messages_log == 0] = 1e-30

                return np.asarray(np.sum(out_messages_log[:2], axis=1))
            else:
                incoming_messages.append(np.asarray([1.0, 1.0]))
                incoming_messages_array = np.asarray(incoming_messages).reshape(
                    len(incoming_messages), 2
                )

                out_messages = array_utils.normalize(
                    node_belief * np.prod(incoming_messages_array, axis=0)
                )
                return np.sum(out_messages, axis=1)

    def compute_out_messages_ct_tree(self, node: int):
        prot_prob_list: List[npt.NDArray[np.float64]] = []
        old_prot_prob_list: List[npt.NDArray[np.float64]] = []
        shared_likelihoods: npt.NDArray[np.float64] = np.ones(self.number_of_parents[node] + 1)
        old_shared_likelihoods: npt.NDArray[np.float64] = np.empty(1)
        peptides: List[int] = []
        prot_list: List[int] = []

        for node_in_neighbour_index, node_in in enumerate(self.neighbours[node]):
            if self.categories[node_in] != Category.factor:
                prot_prob_list.append(self.msg_in[node][node_in_neighbour_index])
                old_prot_prob_list.append(self.msg_in_log[node][node_in_neighbour_index])
                prot_list.append(node_in)
            else:
                peptides.append(node_in)
                try:
                    shared_likelihoods = np.multiply(
                        array_utils.avoid_underflow(shared_likelihoods), self.msg_in[node][node_in_neighbour_index]
                    )
                except:
                    print(shared_likelihoods, self.msg_in[node][node_in_neighbour_index])
                old_shared_likelihoods = np.multiply(
                    array_utils.avoid_underflow(shared_likelihoods), self.msg_in_log[node][node_in_neighbour_index]
                )

        if (
                not np.array_equal(old_shared_likelihoods, shared_likelihoods) and
                any(
                    prot_prob_list[i][0] != old_prot_prob_list[i][0]
                    for i in range(len(prot_prob_list))
                )
        ):
            # only update when the shared likelihoods or at least one of the protein messages has changed
            ct = ConvolutionTree(shared_likelihoods, prot_prob_list)

            for protein_id, protein in enumerate(prot_list):
                node_neighbour_index = self.neighbours[protein].index(node)
                self.msg_in_new[protein][node_neighbour_index] = ct.message_to_variable(protein_id)
                msg = self.msg_in_new[protein][node_neighbour_index]
                if not np.all(msg):
                    self.msg_in_new[protein][node_neighbour_index][
                        msg == 0
                        ] = 1e-30

            for pep in peptides:
                node_neighbour_id = self.neighbours[pep].index(node)
                self.msg_in_new[pep][node_neighbour_id] = ct.message_to_shared_likelihood()
                msg = self.msg_in_new[pep][node_neighbour_id]
                if not np.all(msg):
                    self.msg_in_new[pep][node_neighbour_id][msg < 1e-30] = 1e-30

        else:
            for protein in prot_list:
                node_neighbour_id = self.neighbours[protein].index(node)
                self.msg_in_new[protein][node_neighbour_id] = self.msg_in[protein][node_neighbour_id]

            for pep in peptides:
                node_neighbour_id = self.neighbours[pep].index(node)
                self.msg_in_new[pep][node_neighbour_id] = self.msg_in[pep][node_neighbour_id]

    def compute_infinity_norm_residual(self, node_in: int, node_out: int) -> float:
        node_in_neighbour_id = self.neighbours[node_out].index(node_in)
        msg1 = self.msg_in[node_out][node_in_neighbour_id]
        msg2 = self.msg_in_log[node_out][node_in_neighbour_id]

        if len(msg2) != len(msg1):
            msg2 = [1] * len(msg1)

        pos = 0
        for i in msg1:
            if i < 1e-30:
                msg1[pos] = 1e-30
            pos += 1

        return np.max(np.abs(np.log(np.divide(msg1, msg2))))
        # approximate residual with zero look-ahead

    def compute_total_residuals(self, edge_id: int, current_residual: float):
        start_node, end_node = self.edges[edge_id]
        end_node_neighbor_id: int = self.neighbours[start_node].index(end_node)
        for start_neighbour in self.neighbours[start_node]:
            if start_neighbour != end_node:
                self.total_residuals[self.edge_ids[(start_neighbour, start_node)]][end_node_neighbor_id] = 0

        for i, end_neighbour in enumerate(self.neighbours[end_node]):
            if end_neighbour != start_node:
                self.total_residuals[edge_id][i] += current_residual

    def compute_priority(self, edge_id: int):
        start_node, end_node = self.edges[edge_id]
        self.priorities[edge_id] = 0

        for i, end_neighbor in enumerate(self.neighbours[end_node]):
            if end_neighbor != start_node:
                neighbor_edge: int = self.edge_ids[(end_node, end_neighbor)]
                self.priorities[neighbor_edge] = np.sum(
                    [
                        self.total_residuals[self.edge_ids[(sum_run, end_node)]][i]
                        for sum_run in self.neighbours[end_node]
                        if sum_run != end_neighbor
                    ]
                )

    # computes new message for a given edge (startname, endname) in the direction startname -> endname
    def single_edge_direction_update(self, start_node: int, end_node: int, checked_cts: set[int]):
        start_node_neighbour_id = self.neighbours[end_node].index(start_node)
        if (
                self.categories[start_node] == self.category
                or self.categories[start_node] == Category.peptide
        ):
            self.msg_in_new[end_node][start_node_neighbour_id] = self.compute_out_message_variable(
                start_node, end_node
            )

        if self.categories[start_node] == Category.convolution_tree and start_node not in checked_cts:
            self.compute_out_messages_ct_tree(start_node)
            checked_cts.add(start_node)

        if self.categories[start_node] == Category.factor:
            self.msg_in_new[end_node][start_node_neighbour_id] = self.compute_out_message_factor(
                start_node, end_node
            )

    # compute updated messages for all edges
    def compute_update(self, local_loops: bool = False):
        checked_cts: set[int] = set()  # keeps track of which CT has already been active

        if local_loops and self.max_val:
            start_node = self.max_val[1]
            for end_node in self.neighbours[self.max_val[1]]:
                self.single_edge_direction_update(start_node, end_node, checked_cts)

        else:
            # update all edges
            for start_node, neighbours in enumerate(self.neighbours):
                for end_node in neighbours:
                    self.single_edge_direction_update(start_node, end_node, checked_cts)

    def get_priority_message(self) -> int:
        self.max_val = self.priorities.top()
        return self.max_val

    def zero_look_ahead_loopy_loop(
            self,
            max_loops: int,
            tolerance: float,
            progress_listener: ZeroLookaheadProgressListener
    ) -> Dict[str, npt.NDArray[np.float64]]:
        """
        Run the zero-look-ahead belief propagation algorithm.
        :param max_loops: int, maximum number of iterations in case of non-convergence
        :param tolerance: float, tolerance for convergence check
        :param progress_listener: ZeroLookaheadProgressListener, progress listener that waits for updates from the running
            belief propagation algorithm.
        """

        max_residual = 100

        # first, do 5 loops where I update all messages
        progress_listener.iterations_updated(0, max_loops)
        for k in range(0, 5):
            self.compute_update()
            self.msg_in_log = [msg_in.copy() for msg_in in self.msg_in]
            self.msg_in = [msg_in.copy() for msg_in in self.msg_in_new]

            progress_listener.iterations_updated(k, max_loops)

        # compute all residuals after 5 runs once (= initialize the residual/priorities vectors)
        residuals = [(edge_id, self.compute_infinity_norm_residual(*edge)) for edge_id, edge in enumerate(self.edges)]

        # set the priority vector once with copy of the previously calculated residuals
        self.priorities = pqdict(residuals, reverse=True)

        k = 5

        # keep track of the nodes of which the incoming messages have changed
        prev_changed = [i for i in range(len(self.msg_in))]

        while k < max_loops and max_residual > tolerance:
            # actual zero-look-ahead-BP part
            priority_message_edge_id = self.get_priority_message()
            max_residual = self.priorities[priority_message_edge_id]
            (start_node, end_node) = self.edges[priority_message_edge_id]

            self.single_edge_direction_update(start_node, end_node, set())

            # TODO: should this not be after updating messages? (uses msg_in and msg_log)
            priority_residual = self.compute_infinity_norm_residual(start_node, end_node)
            for node in prev_changed:
                self.msg_in_log[node] = self.msg_in[node].copy()
            prev_changed = []
            # if the start node is a convolution tree, all the incoming messages of the neighbours can be changed.
            if self.categories[start_node] == Category.convolution_tree:
                for node in self.neighbours[start_node]:
                    prev_changed.append(node)
                    for i, neighbour in enumerate(self.neighbours[node]):
                        self.msg_in[node][i] = self.msg_in_new[node][i]
            else:
                start_node_neighbour_id = self.neighbours[end_node].index(start_node)
                self.msg_in[end_node][start_node_neighbour_id] = self.msg_in_new[end_node][start_node_neighbour_id]
                prev_changed.append(end_node)

            self.compute_total_residuals(
                priority_message_edge_id, priority_residual
            )
            self.compute_priority(priority_message_edge_id)

            # Try not to overwhelm the progress listener with too many messages. That's why only every 5th iteration
            # will be reported.
            if k % 5 == 0:
                progress_listener.iterations_updated(k, max_loops)

            k += 1

        # marginalize once the model has converged
        for (node_id, node_category) in enumerate(self.categories):
            if (
                    node_category == self.category
                    or node_category == Category.peptide
            ):
                incoming_messages: List[npt.NDArray[np.float64]] = []

                for incoming_message in self.msg_in[node_id]:
                    incoming_messages.append(
                        incoming_message
                    )

                # log to avoid overflow
                incoming_messages_array = np.log(incoming_messages).reshape(
                    len(incoming_messages), 2
                )
                logged_variable_marginal = array_utils.log_normalize(
                    np.log(self.initial_beliefs[node_id]) + np.sum(incoming_messages_array, axis=0)
                )

                self.current_beliefs[node_id] = logged_variable_marginal

        # Translate the node_ids back to their original sequences and return the current beliefs as a dictionary
        output_beliefs: Dict[str, npt.NDArray[np.float64]] = {}
        for (node_id, beliefs) in enumerate(self.current_beliefs):
            output_beliefs[self.node_id_to_description[node_id]] = beliefs
        return output_beliefs


# calibration through message passing of all subgraphs in the List of factor graphs
def calibrate_all_subgraphs(
        list_of_ct_factor_graphs: List[CTFactorGraph],
        max_iterations: int,
        tolerance: float,
        progress_listener: ZeroLookaheadProgressListener
) -> Tuple[Dict[str, npt.NDArray[np.float64]], Dict[str, str]]:
    """
    Performs bayesian inference through loopy belief propagation, returns dictionary {variable:posterior_probability}
    :param list_of_ct_factor_graphs: list, contains FactorGraph objects on which inference can be performed
    :param max_iterations: int, max number of iterations in case of non-convergence
    :param tolerance: float, error tolerance between messages for convergence criterion
    :param progress_listener: ZeroLookaheadProgressListener, progress listener that waits for updates from the running
        belief propagation algorithm.
    """

    results_dict: Dict[str, npt.NDArray[np.float64]] = {}
    node_category_dict: Dict[str, str] = {}

    progress_listener.graphs_updated(0, len(list_of_ct_factor_graphs))
    for (idx, graph) in enumerate(list_of_ct_factor_graphs):
        if graph.number_of_nodes() > 2:
            node_category_dict.update(dict(graph.nodes(data="category")))

            initialized_message_object = Messages(graph)
            current_beliefs = initialized_message_object.zero_look_ahead_loopy_loop(
                max_iterations,
                tolerance,
                progress_listener
            )

            results_dict.update(current_beliefs)
        progress_listener.graphs_updated(idx + 1, len(list_of_ct_factor_graphs))
    return results_dict, node_category_dict


def convert_results_to_csv(results_dict: Dict[str, npt.NDArray[np.float64]], node_dict: Dict[str, str]):
    """
    Save Loopy Belief Propagation results to .csv file
    :param results_dict: dict, {variable:posterior_probability}
    :param node_dict: dict, dictionary of nodes that were in the factor graph and their attributes, to include the node category in the results
    """

    full_results_dict = {
        key: [results_dict[key][1], node_dict[key]] for key in results_dict.keys()
    }

    return pd.DataFrame.from_dict(data=full_results_dict, orient="index").to_csv(header=False)


def run_belief_propagation(
        graphml_content: str,
        alpha: float,
        beta: float,
        regularized: bool,
        prior: float,
        max_iter: int = 10000,
        tol: float = 0.006,
        progress_listener: ZeroLookaheadProgressListener = PrintZeroLookaheadProgressListener()
    ):
    """
    Runs the belief propagation algorithm on a graph that's represented by the string in graphml_content with the
    tuning parameters further specified to this function. This function returns a string that contains the result of
    the belief propagation algorithm, represented as a CSV (and can thus directly be written to a CSV-file, if desired).
    """

    ct_factor_graph = CTFactorGraph(graphml_content)
    ct_factor_graph.fill_in_factors(alpha, beta, regularized)
    ct_factor_graph.fill_in_priors(prior)
    ct_factor_graph.add_ct_nodes()

    ct_factor_graphs = [
        separate_subgraphs(ct_factor_graph, sorted(filter_nodes))
        for filter_nodes in nx.connected_components(ct_factor_graph)
    ]

    results_dict, node_types = calibrate_all_subgraphs(
        ct_factor_graphs,
        max_iter,
        tol,
        progress_listener
    )

    return convert_results_to_csv(results_dict, node_types)
