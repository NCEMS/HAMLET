interface PeptonizerParameterSet {
    alpha: number;
    beta: number;
    prior: number;
}

/**
 * This interface can be implemented and passed onto the invocation of a run of the Peptonizer algorithm. This way,
 * the Peptonizer will update any listener about its progress and what it's currently doing.
 */
interface PeptonizerProgressListener {
    /**
     * This function is called whenever the Peptonizer starts its very first initialization step and notifies any
     * listener of the amount of parametersets that need to be tuned and which parameters are present in this set.
     * This function will typically be called only once during the complete lifetime of the Peptonizer (and more
     * specifically at the very start of the algorithm).
     *
     * @param totalTasks The total number of parameter optimization tasks that will be performed by the Peptonizer.
     * @param taskSpecifications The concrete sets of parameters that will be tuned by the Peptonizer during its
     * lifetime.
     */
    peptonizerStarted(totalTasks: number, taskSpecifications: PeptonizerParameterSet[]): void;

    /**
     * This function is called whenever the whole Peptonizer pipeline has finished all pending tasks and the final
     * results have become available.
     */
    peptonizerFinished(): void;

    /**
     * This function is called when execution of the peptonizer was successfully cancelled.
     */
    peptonizerCancelled(): void;

    /**
     * Is called whenever the Peptonizer starts tuning a new set of parameters. This parameter set is one of the sets
     * that was already announced by the peptonizerStarts method prior to calling this function.
     *
     * @param parameterSet The current set of parameters for which the Peptonizer started the tuning process.
     * @param workerId Unique identifier of the web worker that is currently performing this task.
     */
    taskStarted(parameterSet: PeptonizerParameterSet, workerId: number): void;

    /**
     * Is called whenever the tuning of a parameter set (previously announced by the taskStarted method) has finished.
     *
     * @param parameterSet The current set of parameters for which the Peptonizer finished the tuning process.
     * @param workerId Unique identifier of the web worker that finished this task.
     */
    taskFinished(parameterSet: PeptonizerParameterSet, workerId: number): void;

    /**
     * Called when the number of graphs that's being processed changes.
     *
     * @param currentGraph
     * @param totalGraphs
     * @param workerId
     */
    graphsUpdated(currentGraph: number, totalGraphs: number, workerId: number): void;

    /**
     * Called whenever the Peptonizer reaches a new "best residual" value during its tuning process.
     *
     * @param maxResidual The current maximum residual value that was encountered in this iteration.
     * @param tolerance If maxResidual goes below this tolerance value, the algorithm assumes convergence of the
     * graph has been achieved and stops running more iterations.
     * @param workerId Unique identifier of the web worker that is currently performing this task.
     */
    maxResidualUpdated(maxResidual: number, tolerance: number, workerId: number): void;

    /**
     * Called whenever the Peptonizer starts working on a new iteration of the belief propagation algorithm.
     *
     * @param currentIteration The current iteration that the Peptonizer started working on.
     * @param totalIterations The maximum number of iterations that will be performed. If no convergence has been
     * achieved when the last iteration starts, the Peptonizer will stop and return the final (non-converged) results.
     * @param workerId Unique identifier of the web worker that is currently performing this task.
     */
    iterationsUpdated(currentIteration: number, totalIterations: number, workerId: number): void;
}

export type { PeptonizerProgressListener, PeptonizerParameterSet };
