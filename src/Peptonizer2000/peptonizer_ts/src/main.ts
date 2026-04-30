import './style.css'
import typescriptLogo from "./typescript.svg"
import peptonizerLogo from "./peptonizer.jpg"
import {PeptonizerParameterSet, PeptonizerProgressListener} from "./PeptonizerProgressListener.ts";
import { Peptonizer } from "./Peptonizer.ts";
import {PeptonizerInputParser} from "./PeptonizerInputParser.ts";

document.querySelector<HTMLDivElement>('#app')!.innerHTML= `
  <div id="app">
    <div>
      <img src="${peptonizerLogo}" class="logo" alt="Peptonizer logo" />
      <a href="https://developer.mozilla.org/en-US/docs/Web/JavaScript" target="_blank">
        <img src="${typescriptLogo}" class="logo vanilla" alt="JavaScript logo" />
      </a>
      <h1>Peptonizer2000</h1>
      
      <div id="inputs">
        <div style="margin: 16px;">
            <span>1. Upload a TSV file</span>
            <label for="file-input" class="file-label">⇪ Choose TSV File</label>
            <input type="file" id="file-input" accept=".tsv,.txt" />
            <div id="file-input-label"></div>
        </div>
               
        <div style="margin: 8px;">
            <span>2. Start the Peptonizer!</span>    
            <button id="peptonize-button" disabled>↯ Start to Peptonize!</button>
        </div>
      </div>
      
      <div id="loading-spinner" hidden>
          <div class="lds-roller"><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div></div>
          <div>Processing...</div>
          <div id="progress-view" style="display: flex;"></div>
          <button id="cancel-button">Cancel</button>
      </div>
      <div id="result-view" hidden>
          <h2>Final output</h2>
          <div id="peptonizer-chart" style="width:100%; min-width: 1000px; height:400px;"></div>
      </div>
    </div>
  </div>
`

let fileContents = "";

document.querySelector<HTMLDivElement>('#file-input')!.addEventListener('change', (event: Event) => {
    const input = event.target as HTMLInputElement;
    const file = input.files ? input.files[0] : null;

    if (file) {
        const reader = new FileReader();
        reader.onload = function(e: ProgressEvent<FileReader>) {
            fileContents = e.target?.result as string;
            document.querySelector<HTMLButtonElement>('#peptonize-button')!.disabled = false; // Enable the button once the file is read
        }
        reader.readAsText(file);
        document.getElementById("file-input-label")!.innerHTML = "1 file selected"
    }
});


type ProgressViewContainer = {
    gridProgressView: HTMLDivElement,
    graphProgressView: HTMLDivElement,
    residualProgressView: HTMLDivElement,
    iterationsProgressView: HTMLDivElement
}

class ProgressListener implements PeptonizerProgressListener {
    private progressViews: ProgressViewContainer[] = [];

    constructor(
        private progressView: HTMLElement,
        private workerCount: number
    ) {
        this.progressViews = [];
        progressView.innerHTML = '';
        for (let worker = 0; worker < this.workerCount; worker++) {
            const div = document.createElement('div');
            div.className += 'worker-status';
            const workerView = document.createElement('div');
            workerView.innerHTML = `Status for worker ${worker}`;
            const gridProgressView = document.createElement('div');
            const graphProgressView = document.createElement('div');
            const residualProgressView = document.createElement('div');
            const iterationsProgressView = document.createElement('div');

            div.appendChild(workerView);
            div.appendChild(gridProgressView);
            div.appendChild(graphProgressView);
            div.appendChild(residualProgressView);
            div.appendChild(iterationsProgressView);

            this.progressView.appendChild(div);

            this.progressViews.push({
                gridProgressView,
                graphProgressView,
                residualProgressView,
                iterationsProgressView
            });
        }
    }

    peptonizerStarted(totalTasks: number, _taskSpecifications: PeptonizerParameterSet[]): void {
        console.log(`Peptonizer will tune ${totalTasks} sets of parameters.`);
    }

    peptonizerFinished() {
        console.log("Peptonizer finished!");
    }

    peptonizerCancelled() {
        console.log("Peptonizer cancelled!");
    }

    taskStarted(parameterset: PeptonizerParameterSet, workerId: number) {
        console.log(
            `Started new Peptonizer task on worker ${workerId} with parameters α = ${parameterset.alpha}, β = ${parameterset.beta} and γ = ${parameterset.prior}`
        );
    }

    taskFinished(parameterset: PeptonizerParameterSet, workerId: number) {
        console.log(
            `Finished Peptonizer task on worker ${workerId} with parameters α = ${parameterset.alpha}, β = ${parameterset.beta} and γ = ${parameterset.prior}`
        );
    }

    graphsUpdated(
        currentGraph: number,
        totalGraphs: number,
        workerId: number
    ) {
        this.progressViews[workerId].graphProgressView.innerHTML = `Finished processing graph ${currentGraph} / ${totalGraphs}`;
    }

    maxResidualUpdated(
        maxResidual: number,
        tolerance: number,
        workerId: number
    ) {
        this.progressViews[workerId].residualProgressView.innerHTML = `Improved maximum residual metric to ${maxResidual}. Tolerance is ${tolerance}`;
    }

    iterationsUpdated(
        currentIteration: number,
        totalIterations: number,
        workerId: number
    ) {
        this.progressViews[workerId].iterationsProgressView.innerHTML = `Finished iteration ${currentIteration} / ${totalIterations}.`;
    }
}


const startToPeptonize = async function() {
    const resultView: HTMLElement = document.getElementById("result-view")!;
    const inputElement: HTMLElement = document.getElementById("inputs")!;
    const loadingSpinner: HTMLElement = document.getElementById("loading-spinner")!;
    const cancelButton: HTMLElement = document.getElementById("cancel-button")!;

    resultView.hidden = true;
    inputElement.hidden = true;
    loadingSpinner.hidden = false;

    const start = new Date().getTime();

    const alphas = [0.8, 0.9, 0.99];
    const betas = [0.6, 0.7, 0.8, 0.9];
    const priors = [0.3, 0.5];

    const peptonizer = new Peptonizer();

    cancelButton.addEventListener("click", async () => {
        peptonizer.cancel();
        console.log("Cancellation finished...");
    });

    const [peptidesScores, peptidesCounts] = PeptonizerInputParser.parse(fileContents);

    try {
        const peptonizerResult = await peptonizer.peptonize(
            new Map(),
            peptidesScores,
            peptidesCounts,
            alphas,
            betas,
            priors,
            "species",
            50,
            new ProgressListener(document.getElementById("progress-view")!, 2)
        );


        const end = new Date().getTime();
        console.log(`Peptonizer took ${(end - start) / 1000}s.`);

        if (!peptonizerResult) {
            return;
        }

        // Extract entries from the Map, format values, and sort them
        const entries = Array.from(peptonizerResult.entries()).map(
            ([key, value]) => [key, parseFloat(value.toFixed(2))]
        );
        // @ts-ignore
        const sortedEntries = entries.sort((a, b) => b[1] - a[1]);

        // Extract keys and values from the sorted entries
        const labels = sortedEntries.map(entry => entry[0]); // Sorted keys
        const values = sortedEntries.map(entry => entry[1]); // Sorted values

        // Render the chart with Highcharts
        // @ts-ignore
        Highcharts.chart('peptonizer-chart', {
            chart: {
                type: 'bar'
            },
            title: {
                text: 'Peptonizer Confidence Scores'
            },
            xAxis: {
                categories: labels.slice(0, 20),
                title: {
                    text: 'Peptide IDs'
                }
            },
            yAxis: {
                min: 0,
                max: 1,
                title: {
                    text: 'Confidence Score',
                    align: 'high'
                },
                labels: {
                    overflow: 'justify',
                    format: '{value:.3f}'
                }
            },
            tooltip: {
                pointFormat: 'Confidence: <b>{point.y:.2f}</b>'
            },
            plotOptions: {
                bar: {
                    dataLabels: {
                        enabled: true,
                        format: '{y:.3f}'
                    }
                }
            },
            series: [{
                name: 'Confidence score',
                data: values.slice(0, 20)
            }]
        });
    } catch (err) {
        console.log("Error caught in main!");
        console.log(err);
    }

    resultView.hidden = false;
    loadingSpinner.hidden = true;
    inputElement.hidden = false;
}

document.getElementById("peptonize-button")!.addEventListener("click", startToPeptonize);
