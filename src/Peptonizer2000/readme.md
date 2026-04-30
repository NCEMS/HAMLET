<div id="top"></div>


<!-- PROJECT SHIELDS -->
<!--
*** I'm using markdown "reference style" links for readability.
*** Reference links are enclosed in brackets [ ] instead of parentheses ( ).
*** See the bottom of this document for the declaration of the reference variables
*** for contributors-url, forks-url, etc. This is an optional, concise syntax you may use.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
-->
<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href=https://git.bam.de/tholstei/pepgm/>
    <img src="https://raw.githubusercontent.com/compomics/Peptonizer2000/refs/heads/master/peptonizer_logo.jpg" alt="Logo"  height="300">
  </a>

<h3 align="center">The Peptonizer 2000</h3>

  <p align="center">
    Integrating PepGM and Unipept for probability-based taxonomic inference of metaproteomic samples
    <br />
  </p>
</div>


<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
      </ul>
    </li>
    <li><a href="#input">Input</a></li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
        <li><a href="#preparation">Preparation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

Introducing the Peptonizer2000 - a tool that combines the capabilities of Unipept and PepGM to analyze
metaproteomic mass spectrometry-based samples. Originally designed for taxonomic inference of viral
mass spectrometry-based samples, we've extended PepGM's functionality to analyze metaproteomic samples by
retrieving taxonomic information from the Unipept database.

PepGM is a probabilistic graphical model developed by Tanja Holstein et al. that uses belief propagation to infer the taxonomic origin of peptides and taxa in viral samples.
You can learn more about PepGM at [GitHub](https://github.com/BAMeScience/PepGM) page.

Unipept, on the other hand, is a web-based metaproteomics analysis tool that provides taxonomic information for
identified peptides. To make it work seamlessly with PepGM, we've extended Unipept with new functionalities that
restrict the taxa queried and provide all potential taxonomic origins of the peptides queried. Check out more
information about Unipept [here](https://unipept.ugent.be/).

With the Peptonizer2000, you can look forward to a comprehensive and streamlined workflow that simplifies
the process of identifying peptides and their taxonomic origins in metaproteomic samples.

The Peptonizer2000 workflow is comprised of the following steps:

1. Query all identified peptides, provided by the user in a .tsv file, in the Unipept API,
   and restrict the taxonomic range queried based on any prior knowledge of the sample.
2. Assemble the peptide-taxon associations provided by Unipept into a bipartite graph,
   where peptides and taxa are represented by different nodes, and an edge is drawn between a peptide and a taxon
   if the peptide is part of the taxon's proteome.
3. Transform the bipartite graph into a factor graph using convolution trees and conditional probability table
   factors (CPD).
4. Run the belief propagation algorithm multiple times with different sets of CPD parameters until convergence,
   to obtain posterior probabilities of candidate taxa.
5. Use an empirically deduced metric to determine the ideal graph parameter set.
6. Output the top scoring taxa as a results barchart. The results are also available as comma-separated files
   for further downstream analysis or visualizations.


<div align="center">
    <img src="https://raw.githubusercontent.com/compomics/Peptonizer2000/refs/heads/master/peptonizer_workflow.png" alt="workflow scheme" width="500">
</div>

<br>



<p align="right">(<a href="#top">back to top</a>)</p>

<!-- INPUT -->

## Input

* A .tsv file of your peptides output from any protoemic peptide search method. The first column should be the peptide, the second column it's score attributed by the search engine. An example is provided in test files. <br>
* A config file with your parameters for the peptonizer2000. A more detailed description of the configuration file can be found below. Additionally, an exemplary config file is provided in this repository.

<p align="right">(<a href="#top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

### Prerequisites

## Python counterpart
The actual code that builds the factor graph and executes the Peptonizer algorithm, is implemented in Python and can be found in the `peptonizer` folder.

### Running as snakemake workflow
In order to run the Peptonizer2000 on your own system, you should install Conda, Mamba and all of its dependencies.
Follow the installation instructions step-by-step for an explanation of what you should do.

* Make sure that Conda and Mamba are installed. If these are not yet present on your system, you can follow the instructions on their [README](https://github.com/conda-forge/miniforge).
* Go to the "workflow" directory by executing `cd snakemake/workflow` from the terminal.
* Run `conda env create -f env.yml` (make sure to run this command from the workflow directory) in order to install all dependencies and create a new conda environment (which is named "peptonizer" by default).
* Run `mamba install -c conda-forge -c bioconda -n peptonizer snakemake` to install snakemake which is required to run the whole workflow from start-to-finish.
* Run `conda activate peptonizer` to switch the current Conda environment to the peptonizer environment you created earlier.
* Start the peptonizer with the command `snakemake --use-conda --cores 1`. If you have sufficient CPU and memory power available to your system, you can increase the amount of cores in order to speed up the workflow.


### Configuration file

The Peptonizer2000 relies on a configuration file in `yaml` format to set up the workflow.
An example configuration file is provided in `config/config.yaml`. <br>
Do not change the config file location.

<details> 
   <details > <summary> Directory parameters </summary>
   <ul>
      <li>data_dir: relative path to output files </li>
      <li>input_file: relative path to input .tsv </li> 
      <li>log_dir: relative path to log directory</li>
   </ul>
   </details>

   <details > <summary> Analysis specific parameter </summary>
   <ul>
      <li>taxa_in_graph: # of inferred taxa that appear in the barplot that is created of the results csv</li>
      <li>taxa_in_plot: number of taxa reported in bar plot</li>
      <li>alpha: grid search increments for alpha (list) </li>
      <li>beta: grid search increments for beta (list) </li>
      <li>prior: grid search increments for prior (list) </li>
      <li>regularized: boolean. If True, the probability for the number of parents taxa of a peptide is regularized to be inversely proportional to the number of parents </li>
   </ul>
   </details>
   <details > <summary> UniPept query parameters </summary>
   <ul>
       <li>taxon_rank: rank at which results will be reported </li>
       <li>taxon_query: taxa comprised in the UniPept query. If querying all of Unipept, use 1 (list)</li>
   </ul> 
   </details>
</details>

### Output files

All Peptonizer2000 output files are saved into the results folder and include the following: <br>

Main results: <br>

- peptonizer_results.csv: table with values ID, score, type (contains all taxids under 'ID' and all probabilities under 'score' <br>
- peptonizer_results.png: bar plot of the peptonizer results showing the scores for the #'taxa_in_plot' (see config parameters) highest scoring taxa
  <br>

Additional files: <br>
- Intermediate results folders sorted by their prior value for all possible grid search parameter combinations
- taxa_weights_dataframe.csv: csv file of all taxids that had at least one peptide map to them and their weight 
- pepgm_graph.graphml: graphml file of the graphical model (without convolution tree factors). Useful to visualize the graph structure and peptide-taxon connections <br>
- sequence_scores_dataframe.csv: dataframe with petides, taxa and scores used to create the graph <br>
- best_parameter.csv: file with best parameter <br>
- unipept_responses.json: response of unipept queries <br>
- clustered_taxa_weights_datatframe: additional .csv file resulting from the clustering of taxa by peptidome used for rbo<br>


<p align="right">(<a href="#top">back to top</a>)</p>


## Testing the Peptonizer
<!-- Testing -->

To test the Peptonizer2000 and see if it is set up correctly on your machine, we provide a test file under resources/test_files. This should be dowloaded automatically if you follow the installation instructions above. There are several test files from different metaproteomic samples. These are: <br>
- the samples S03, S05 and S11 of the [CAMPI study](https://www.nature.com/articles/s41467-021-27542-8) searched against a sample specific database using X!Tandem and MS2Rescore. The original files are available through [PRIDE under PXD023217](https://www.ebi.ac.uk/pride/archive/projects/PXD023217/). 
- the sample U1 of uneven communities from a [metaproteomic benchmark study by Kleiner](https://www.nature.com/articles/s41467-017-01544-x) searched against a sample specific database. The original files are available through [PRIDE under PXD006118](https://www.ebi.ac.uk/pride/archive/projects/PXD006118)
- the sample F07, a fecal sample, of the [CAMPI study](https://www.nature.com/articles/s41467-021-27542-8) searched against the integrated gene catalog for the human gut using X!Tandem and MS2Rescore. The original files are available through [PRIDE under PXD023217](https://www.ebi.ac.uk/pride/archive/projects/PXD023217/). 

To execute a test run of the Peptonizer2000 using the provided files: 
 
 1. Follow the installation instructions above
 2. In the config file, make sure to point to the test sample you want to use. By default, this is S03
 3. Start to peptonize with the command `snakemake --use-conda --cores 1`. If you have sufficient CPU and memory power available to your system, you can increase the amount of cores in order to speed up the workflow.


<!-- LICENSE -->
## License

Distributed under the Apache 2.0 License. See `LICENSE.txt` for more information.

<p align="right">(<a href="#top">back to top</a>)</p>


<!-- CONTACT -->
## Contact

Tanja Holstein - [@HolsteinTanja](https://twitter.com/HolsteinTanja) - tanja.holstein@ugent.be <br>
Pieter Verschaffelt - pieter.verschaffelt@ugent.be

<div align="center">
  <img src="https://raw.githubusercontent.com/compomics/Peptonizer2000/refs/heads/master/peptonizer_developers.jpeg" alt="Logo"  height="300">
</div>

<p align="right">(<a href="#top">back to top</a>)</p>


<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/BAMeScience/repo_name.svg?style=for-the-badge
[contributors-url]: https://github.com/BAMeScience/repo_name/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/BAMeScience/repo_name.svg?style=for-the-badge
[forks-url]: https://github.com/BAMeScience/repo_name/network/members
[stars-shield]: https://img.shields.io/github/stars/BAMeScience/repo_name.svg?style=for-the-badge
[stars-url]: https://github.com/BAMeScience/repo_name/stargazers
[issues-shield]: https://img.shields.io/github/issues/BAMeScience/repo_name.svg?style=for-the-badge
[issues-url]: https://github.com/BAMeScience/repo_name/issues
[license-shield]: https://img.shields.io/github/license/BAMeScience/repo_name.svg?style=for-the-badge
[license-url]: https://github.com/BAMeScience/repo_name/blob/master/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/linkedin_username
[product-screenshot]: images/screenshot.png
[Next.js]: https://img.shields.io/badge/next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white
[Next-url]: https://nextjs.org/
[React.js]: https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB
[React-url]: https://reactjs.org/
[Vue.js]: https://img.shields.io/badge/Vue.js-35495E?style=for-the-badge&logo=vuedotjs&logoColor=4FC08D
[Vue-url]: https://vuejs.org/
[Angular.io]: https://img.shields.io/badge/Angular-DD0031?style=for-the-badge&logo=angular&logoColor=white
[Angular-url]: https://angular.io/
[Svelte.dev]: https://img.shields.io/badge/Svelte-4A4A55?style=for-the-badge&logo=svelte&logoColor=FF3E00
[Svelte-url]: https://svelte.dev/
[Laravel.com]: https://img.shields.io/badge/Laravel-FF2D20?style=for-the-badge&logo=laravel&logoColor=white
[Laravel-url]: https://laravel.com
[Bootstrap.com]: https://img.shields.io/badge/Bootstrap-563D7C?style=for-the-badge&logo=bootstrap&logoColor=white
[Bootstrap-url]: https://getbootstrap.com
[JQuery.com]: https://img.shields.io/badge/jQuery-0769AD?style=for-the-badge&logo=jquery&logoColor=white
[JQuery-url]: https://jquery.com 

