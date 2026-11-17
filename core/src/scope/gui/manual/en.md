## Welcome

**SCOPE** prepares, submits and tracks quantum-chemistry calculations (Gaussian 16 and Quantum ESPRESSO) for molecules and molecular crystals. This window guides you through it in five steps. You can go through them in order with the **Next** button, or jump to any step in the left bar.

| Step | What you do | What SCOPE needs |
|---|---|---|
| 1 Environment | Say where your files live | three folders and a name |
| 2 Systems | Bring in the molecules to compute | `.xyz` files |
| 3 Pipeline | Describe what to compute, and in what order | input files (`.scope`) |
| 4 Run | Let SCOPE act on the pipeline | an environment, a system and input files |
| 5 Cluster | Run on a remote cluster instead of this computer | an SSH connection |

A green dot next to a step means it is done. A step is never locked: the dots only tell you what is still missing.

**SCOPE on this computer.** Under the SCOPE title at the top of the left bar a light shows whether SCOPE is installed and can be started from this window, with the installed version. This window is part of SCOPE and starts `scope run` in a separate process, so it needs SCOPE in the same Python.

| Light | Meaning |
|---|---|
| Green | SCOPE is active: it imports, a run can start, and Python is 3.12. |
| Amber | SCOPE runs, but on another Python than 3.12, which SCOPE does not support. |
| Red | SCOPE cannot be started from this Python. |

The version is read from the installation each time, never stored, so it follows an upgrade: the check runs when the window opens, when you come back to it after a few minutes, and when you press **Check again**. Click the light for the details (Python, SCOPE and where it is installed, whether the `scope` command exists in a Terminal, cell2mol, rdkit, the settings folder) and, if something is missing, the installation commands.

> **Good to know.** On a computer without a job scheduler (a laptop, for instance) SCOPE builds the workflow and registers results that already exist, but it does **not** write calculation inputs or run anything. Computing happens on a cluster (step 5). This is how SCOPE itself works, not a limit of the GUI.

## Quick start

1. **Environment**: choose a project folder, for instance `~/scope_project`, and press *Create local environment*.
2. **Systems**: press *Import .xyz…* and choose a molecule.
3. **Pipeline**: press *New input…*, fill in the form, save. Add a second input for the next calculation and list the first one under *Requisites*.
4. **Run**: choose the system and press *Run*.
5. **Cluster** (optional): add your cluster, press *Test connection*, then upload, run and download.

## How SCOPE thinks

| Word | Meaning |
|---|---|
| **Environment** | Where things are: three folders (sources, systems, computations) and, on a cluster, the scheduler, queues and software modules. Saved as `scope_env_<name>.npy`. |
| **Source** | A structure: a molecule or a crystal cell, normally read from an `.xyz` file. |
| **System** | The project container for one chemical entity. It holds its sources and all calculations done on them. Saved as `Systems/<name>/<name>.npy`. |
| **Branch** | A line of work inside a system (a folder in `Computations/<system>/`). Jobs of one pipeline share a branch. |
| **Workflow** | The set of jobs applied to one source. |
| **Job** | One step of the pipeline, such as an optimization (`opt`) or a frequency calculation (`freq`). |
| **Computation** | One real software run with its input, output and status. A job can create several (retries, continuations). |
| **Input file** | A small text file (`.scope`) that tells SCOPE which job to run, with which software and settings. |

The hierarchy is **System → Branch → Workflow → Job → Computation**.

SCOPE is *incremental*: every time you press Run it looks at what exists, submits what is ready, skips what is running, registers what has finished, and saves. You run it again and again until everything is done.

## 1 · Environment

The environment records three folders:

- **Sources**: your structure files, one subfolder per system.
- **Systems**: one subfolder per system with its `.npy` file.
- **Computations**: one subfolder per system with all inputs and outputs.

Choose a *project folder* and the three subfolders are filled in for you (you may edit them). Press **Create local environment**. The environment file is saved in the project folder.

**Open existing environment…** loads an environment made earlier, for instance on a cluster with `scope config`. If it was created on another computer its folders may not exist here; the summary tells you which are missing.

*Names:* use letters, digits, `_`, `-` or `.`, with no spaces.

> Files with the extension `.npy` are Python "pickle" files. Opening one runs code stored inside it. Open only files you created or trust.

## 2 · Systems

The table lists the systems found in the environment's Systems folder, with the branches that are *finished* or *terminated* (SCOPE marks them with small files named `<branch>_FINISHED` and `<branch>_TERMINATED`).

**Import .xyz…** creates a system from one or more `.xyz` files. The file name (without `.xyz`) becomes the system name, so use letters, digits, `_`, `-` and `.` only: a space in a system name breaks job submission on a cluster. The file is copied into `Sources/<name>/`.

Select a row to read the system's summary: its sources, branches and folders.

## 3 · Pipeline

A pipeline is a set of input files. Each file describes **one job**. The table lists them and the graph shows how they depend on each other, read from left to right: an arrow **A → B** means B starts only after A has finished.

**New input…** opens a form:

- **Branch**: the folder name for this line of work, for example `demo`.
- **Workflow (sources)**: which sources of the system to run. `*` means all, or give a name or a pattern like `water*`, or several names separated by commas.
- **Job name**: `opt`, `freq`, `scf`…
- **Requisites**: jobs that must finish before this one. Empty means *start right away*. A `freq` job after an optimization needs `opt`. Never put the job's own name here: it would wait for itself and never start.
- **Constrains**: jobs that block this one once finished. `self` prevents running the same job twice.
- **Software and computation type**: Gaussian 16 (`g16`: scf, opt, freq, ts, td, tda) or Quantum ESPRESSO (`qe`: scf, opt, relax, vc-relax, freq).
- **Functional, basis set, processors, queue**: chemistry and resources. The queue is optional and, on a cluster, must match one of the environment's queues exactly.
- **Submit**: when ticked the file says `want_submit = True` and SCOPE will submit jobs to the scheduler. Unticked by default.

The text on the right is the file that will be written, and the line under it says whether SCOPE accepts it. Other settings can be added in the tabs below the form, one `key = value` per line. **Edit selected…** reopens a file in the same form (comments in the file are not kept).

Warnings in orange mean SCOPE would accept the file but something looks wrong: a job that requires itself, a requisite that no loaded file defines, two files defining the same job, or a cycle.

## 4 · Run

Choose a **system**, then press **Run**. The log shows what SCOPE does, live. At the end SCOPE prints a *manual attention required* block: read it, it lists what you should check.

- *quiet* prints less, *verbose* prints more.
- *handle errors* lets SCOPE retry some common failures by itself.
- **Stop** asks the run to end (SCOPE continues where it stopped the next time you run).

If the environment has a scheduler and an input has *Submit* on, the Run button asks for confirmation first, because it sends real jobs and uses computing time.

On a local environment you will see `No Queue Management has been detected in cluster, disabling submission`. That is expected: nothing is submitted and no inputs are written.

**A run does not depend on this window.** It is started on its own, writes its output to a log file, and keeps going if you close the window, if the window crashes, or if you press Ctrl-C in the Terminal where you started the window. When you close the window during a run it asks whether to leave the run going (the default) or stop it. When you open the window again it finds the run, shows its log, and tells you if it ended while the window was closed. The logs are in the `gui_runs` folder next to the SCOPE settings (see the details of the SCOPE light).

Run again later to advance the pipeline. Two runs on the same system at the same time can overwrite each other's results: wait for one to finish.

## 5 · Cluster

Most calculations run on a cluster. SCOPE must be installed **on the cluster** and runs there; this window starts it over SSH and moves files with `rsync`. Your SSH setup is used as it is (keys, `~/.ssh/config`, jump hosts) and **no password is ever stored by this program**. Nothing is sent to the cluster until you press a button.

### Before the first test: what must exist on the cluster

1. **SSH works from your Terminal.** `ssh <host>` logs you in (with a key, or with a password or second factor).
2. **SCOPE is installed there**, in its own Python 3.12 environment, for example:

```
conda create --name scope python=3.12
conda activate scope
pip install "cell2mol @ git+https://github.com/lcmd-epfl/cell2mol.git@55649ba5f444895846a5d049adcb056c01bb0421"
pip install scope-qc
```

3. **A cluster environment exists.** On the cluster run `scope config -n cluster`. It asks for the three folders (give it `<project>/Sources`, `<project>/Systems` and `<project>/Computations`, all inside one project folder), detects the scheduler, then asks for the **module names** of Gaussian 16 and Quantum ESPRESSO (press Enter to skip one) and the queues. The result is the file `scope_env_cluster.npy`.

The module names you give there are what SCOPE uses to find Gaussian 16 and Quantum ESPRESSO: see *The three lights* below.

### Set up a profile

A profile is one cluster. Press **New** (or start typing, the first time), fill in the fields, press **Save profile**. The yellow hint under the fields says what is still missing; it turns into a green tick when the profile is complete. Paths start with `/` or `~/`, with no spaces and no `$VARIABLES`.

| Field | What to write | Example |
|---|---|---|
| Profile name | Any label: letters, digits, `_`, `-`, no spaces | `nersc` |
| SSH host | The name you use with `ssh`. The list shows the names found in your `~/.ssh/config`. | `nersc` |
| Path of scope on the cluster | Where the `scope` program is. Prefer this field. | `~/miniconda3/envs/scope/bin/scope` |
| …or a line that makes it available | Only if the path field is empty, for example `module load scope`. `conda activate` often does not work in this kind of shell, which is why the path is preferred. | |
| Project folder on the cluster | The folder that holds `Sources`, `Systems` and `Computations` | `~/scope_project` |
| Cluster environment file | The `scope_env_*.npy` made by `scope config` | `~/scope_project/scope_env_cluster.npy` |

To find the values, log in and run `which scope` (path of `scope`) and `pwd` inside the project folder.

### Password or second factor

This window cannot answer a password or code prompt. Press **Show terminal command**, copy the command, run it once in the Terminal app and log in. It opens a connection that stays open for a few hours; this window then reuses it. Keys without a password need no such step.

### Test connection

Press **Test connection**. It only reads: nothing is changed on the cluster. It checks, one by one:

- SSH and the login shell
- Python on the cluster (SCOPE needs 3.12)
- SCOPE and its version (compared with the version here; a development install reports the same number for different code, so this cannot prove the code is identical)
- the project folder and the cluster environment file, and that the environment's three folders are the `Sources`, `Systems` and `Computations` inside the project folder
- the scheduler commands (`sbatch`, `squeue`, `sinfo` for Slurm; `qsub`, `qstat` for SGE)
- the software, as three lights
- that `TMPDIR` is set (SCOPE's job script needs it)

### The three lights

When the test finishes, three lights show what is available on the cluster, in order of priority: **SCOPE**, **Quantum ESPRESSO**, **Gaussian 16**. They are filled in automatically from the same test; there is nothing more to press. Point the mouse at a light for the details, and read the matching row in the table below it. The time of the last check is shown at the right.

| Light | Meaning |
|---|---|
| Green | Available. SCOPE imports and the cluster environment loads; or the module loads and the program is found. |
| Amber | Found, but incomplete or doubtful (for instance no MPI launcher for Quantum ESPRESSO, or the check could not finish). Read the details. |
| Red | Not available: SCOPE not found; the module name does not load; or the module loads but the program is not in the path. |
| Grey | Not checked yet, or **not set in the cluster environment**. |

**How the check works.** SCOPE itself decides what counts as available, and the window asks SCOPE on the cluster. For Quantum ESPRESSO it loads the module named in the cluster environment (`module load <name>`) and looks for `pw.x`, then for an MPI launcher (`mpirun`, `mpiexec` or `srun`). For Gaussian 16 it loads the module and looks for `g16`. No program is run, no job is submitted, no MPI rank is started. Software that is installed on the cluster but not named in the cluster environment shows grey, because SCOPE would not use it: run `scope config` again on the cluster and give the module name.

The lights are a snapshot. They change only when you press Test connection again; the window never contacts the cluster on its own. Before **Run on the cluster**, the window warns you if an input file needs software whose light is red or grey.

### Everyday use

- **Preview upload** lists what would be copied (nothing is copied). **Upload** copies the selected system and the input files. Generated calculation files are never uploaded: SCOPE writes them on the cluster.
- **Run on the cluster** starts `scope run` there and shows the log here. SCOPE first runs `scope set_path` so that the paths stored in the system match the cluster folders. It asks you to confirm, and says whether input files will submit jobs.
- **The run is detached.** It is started on the cluster with its own log and process (in `<project>/logs/`), so it keeps going if you close this window, if the window crashes, or if the connection drops. Jobs already handed to the scheduler are never affected by the window. A second run of the same system is refused while one is active, because two runs can overwrite each other's results.
- **Watch runs** finds a run that is active on the cluster, for example one started before the window was closed, and follows its log. After a passed connection test the window also tells you if a run is active. **Stop watching** only stops following; the run goes on. **Stop the run** asks the cluster to end it (jobs already submitted are not cancelled).
- **Preview download** / **Download** bring results back. Large files (wavefunctions, scratch, checkpoints) are skipped by default. A download can replace the local system file: look at the preview first.

## Local and cluster: what works where

| | This computer (no scheduler) | Cluster (Slurm or SGE) |
|---|---|---|
| Create environments, systems, input files | yes | yes |
| Draw the pipeline | yes | yes |
| Write calculation inputs and job scripts | **no** | yes, when *Submit* is on |
| Submit and run calculations | **no** | yes |
| Register finished outputs | yes (if the files are here) | yes |
| Look at results | yes | yes |

Gaussian 16 and Quantum ESPRESSO 7.0 are supported. ORCA and VASP are not.

## Input file reference

An input file has four sections, each between `&name` and `/`.

```
&environment
   requested_procs = 4
/
&options
   want_submit = False
/
&job_data
   branch     = 'demo'
   workflow   = '*'
   job        = 'opt'
   hierarchy  = 1
   requisites = []
   constrains = ['self']
/
&qc_data
   software   = 'g16'
   comp_type  = 'opt'
   functional = 'b3lyp'
   basis      = '6-31g*'
/
```

| Section | Common keys |
|---|---|
| `&environment` | `requested_procs`, `queue`, `time_limit` (minutes), `max_jobs`, `max_procs` |
| `&options` | `want_submit`, `ignore_submitted`, `overwrite_inputs`, `overwrite_outputs` |
| `&job_data` | `branch`, `workflow`, `job`, `requisites`, `constrains`, `istate`, `fstate`, `job_setup`, `save_wf` |
| `&qc_data` | `software`, `comp_type`, `functional`, `basis` (Gaussian), `pp_library`, `mix_beta`, `elec_conv` (Quantum ESPRESSO) and more |

Things worth knowing:

- Lines starting with `#` are comments. SCOPE turns most values to lower case, so `'6-31G*'` and `'6-31g*'` are the same, but branch names keep their case.
- If `want_submit` is missing SCOPE assumes **True**. The form always writes it.
- SCOPE checks the software and the computation type, but **not** the functional or basis set: a typo shows up only when the calculation fails.

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| The light under SCOPE is red | SCOPE cannot be imported by the Python that runs this window | Click the light, copy the installation commands, install SCOPE in that environment and press *Check again* |
| I closed the window (or it crashed) during a run | Nothing is lost: runs are independent of the window | Open the window again: it finds the run. On the Cluster page press *Watch runs* |
| The window did not appear | On macOS a window started from a terminal can open behind other apps | Press Cmd+Tab and choose *Python* |
| A job never starts and SCOPE says `requisites NOT met` | The job lists itself, or a job that never finishes, as a requisite | Edit the input; requisites are jobs that must finish **before** this one |
| `scope run` stops with `EOFError` | An input names a queue that only partly matches (`shor` for `short`), and SCOPE asks a question that cannot be answered here | Use the exact queue name |
| A system name with a space | Job submission splits the name in two | Rename the `.xyz` file, no spaces |
| Environment shows *folder(s) not found* | The environment was made on another computer | Create a local one, or open the cluster one on the cluster |
| Nothing is written when you Run on your own computer | There is no scheduler, so SCOPE does not generate inputs | Use the Cluster step |
| Cluster test fails at *SSH* | Host unknown, key not loaded, or password/2FA needed | Check `~/.ssh/config`; for 2FA use *Show terminal command* |
| A light is grey: *not set* | The cluster environment names no module for that software | On the cluster run `scope config` again and give the module name |
| A light is red: *module fails* | The module name in the cluster environment is wrong or not loadable | `module avail` on the cluster, then correct it with `scope config` |
| Quantum ESPRESSO is amber: *no MPI launcher* | `pw.x` was found but no `mpirun`, `mpiexec` or `srun` is visible after loading the module | Check the module; ask the cluster support which launcher to use |
| Profile hint: *Write the path starting with / or ~/* | The path is relative, has spaces or a `$VARIABLE` | Use `/home/you/...` or `~/...` |
| Cluster job fails immediately with `TMPDIR: parameter null or not set` | SCOPE's job script needs the variable `TMPDIR` on the compute node | Ask the cluster support, or set it in your shell profile |

## Glossary

**Branch**, **Computation**, **Environment**, **Input file**, **Job**, **Source**, **System**, **Workflow**: see *How SCOPE thinks*. **Queue / partition**: a group of cluster nodes with its own limits. **Scheduler**: the cluster program that decides when jobs run (Slurm or SGE). **Module**: the cluster's way to make a program available (`module load gaussian/16`). **Pickle / `.npy` file**: SCOPE's saved objects; open only trusted ones.

## About this GUI

This interface calls the same SCOPE functions as the command line (`scope config`, `scope create_single`, `scope run`, `scope set_path`) and starts `scope run` as a separate process, so closing the window while a run is active asks you first. The look follows your system or the choice made with the sun/moon button at the bottom of the left bar.
