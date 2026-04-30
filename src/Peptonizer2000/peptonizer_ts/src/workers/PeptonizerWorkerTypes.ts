// Define a specific type of inputs that are expected for each task that can be performed by this worker.
enum WorkerTask {
    PERFORM_TAXA_WEIGHING,
    GENERATE_GRAPH,
    EXECUTE_PEPGM,
    CLUSTER_TAXA,
    COMPUTE_GOODNESS
}

interface PerformTaxaWeighingTaskData {
    peptidesTaxa: Map<string, number[]>;
    peptidesScores: Map<string, number>;
    peptidesCounts: Map<string, number>;
    rank: string;
    taxaInGraph: number;
}

interface GenerateGraphTaskData {
    taxaWeightsCsv: string;
}

interface ExecutePepgmTaskData {
    graphXml: string,
    alpha: number,
    beta: number,
    prior: number,
}

interface ClusterTaxaTaskData {
    graphXml: string,
    taxaWeightsCsv: string,
    similarityThreshold: number
}

interface ComputeGoodnessTaskData {
    clusteredTaxaWeightsCsv: string,
    peptonizerResults: Map<string, number>
}

type SpecificInputEventData =
    { task: WorkerTask.PERFORM_TAXA_WEIGHING, input: PerformTaxaWeighingTaskData } |
    { task: WorkerTask.GENERATE_GRAPH, input: GenerateGraphTaskData } |
    { task: WorkerTask.EXECUTE_PEPGM, input: ExecutePepgmTaskData } |
    { task: WorkerTask.CLUSTER_TAXA, input: ClusterTaxaTaskData } |
    { task: WorkerTask.COMPUTE_GOODNESS, input: ComputeGoodnessTaskData };

type CommonInputEventData = { workerId: number };

type InputEventData = SpecificInputEventData & CommonInputEventData;

interface PerformTaxaWeighingTaskResult {
    sequenceScoresCsv: string,
    taxaWeightsCsv: string
}

interface GenerateGraphTaskDataResult {
    graphXml: string
}

interface ExecutePepgmTaskDataResult {
    taxonScoresJson: string
}

interface PepgmProgressUpdate {
    progressType: "graph" | "max_residual" | "iteration",
    currentValue: number,
    maxValue: number
}

interface ClusterTaxaTaskDataResult {
    clusteredTaxaWeightsCsv: string
}

interface ComputeGoodnessDataResult {
    goodness: number
}

enum ResultType {
    SUCCESSFUL,
    PROGRESS,
    FAILED,
    CANCELLED
}

type SpecificOutputEventData = { resultType: ResultType.SUCCESSFUL } & (
    { task: WorkerTask.PERFORM_TAXA_WEIGHING, output: PerformTaxaWeighingTaskResult } |
    { task: WorkerTask.GENERATE_GRAPH, output: GenerateGraphTaskDataResult } |
    { task: WorkerTask.EXECUTE_PEPGM, output: ExecutePepgmTaskDataResult } |
    { task: WorkerTask.CLUSTER_TAXA, output: ClusterTaxaTaskDataResult } |
    { task: WorkerTask.COMPUTE_GOODNESS, output: ComputeGoodnessDataResult });

type CommonOutputEventData = { workerId: number };

type ErrorOutputEvent = { resultType: ResultType.FAILED, error: string };
type ProgressOutputEvent = { resultType: ResultType.PROGRESS, task: WorkerTask.EXECUTE_PEPGM, progressUpdate: PepgmProgressUpdate };

type OutputEventData = (SpecificOutputEventData | ErrorOutputEvent | ProgressOutputEvent) & CommonOutputEventData;

export {
    WorkerTask,
    ResultType
};

export type {
    PerformTaxaWeighingTaskData,
    GenerateGraphTaskData,
    ExecutePepgmTaskData,
    ClusterTaxaTaskData,
    ComputeGoodnessTaskData,
    SpecificInputEventData,
    InputEventData,
    PerformTaxaWeighingTaskResult,
    GenerateGraphTaskDataResult,
    ExecutePepgmTaskDataResult,
    ClusterTaxaTaskDataResult,
    ComputeGoodnessDataResult,
    OutputEventData,
    PepgmProgressUpdate,
    ProgressOutputEvent
};
