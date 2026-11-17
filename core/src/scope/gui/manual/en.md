# Getting started

## Welcome

SCOPE prepares, submits and tracks quantum-chemistry calculations (Gaussian 16 and Quantum ESPRESSO) for molecules and molecular crystals. This window guides you through the work in five steps.

| Step | What you do | What SCOPE needs |
|---|---|---|
| 1 Environment | Say where your files live | Three folders and a name |
| 2 Systems | Bring in the molecules to compute | `.xyz` files |
| 3 Pipeline | Describe what to compute, and in what order | Input files (`.scope`) |
| 4 Run | Let SCOPE act on the pipeline | An environment, a system and input files |
| 5 Cluster | Run on a remote cluster instead of this computer | An SSH connection |

Go through the steps in order with the **Next** button, or jump to any step in the left bar. A green dot next to a step means it is done. Steps are never locked: the dots only show what is still missing.

> **Note.** On a computer without a job scheduler (a laptop, for instance) SCOPE builds the workflow and registers results that already exist, but it does not write calculation inputs or run anything. Computing happens on a cluster (step 5). This is how SCOPE itself works, not a limit of this window.

Under the **SCOPE** title at the top of the left bar, a light shows whether SCOPE can be started from this window. It is explained in *Install and start*.

## Install and start

Open the window with the launcher if you cloned the repository, or with `scope gui` if SCOPE is already installed in your own Python 3.12 environment.

### From a source checkout

The launcher sits in the top folder of the repository. It prepares everything on the first start, so there is nothing to set up by hand.

| System | Command |
|---|---|
| macOS, Linux | `./scope-gui` |
| Windows | `scope-gui.bat` |

On the first start the launcher:

1. finds a Python 3.12 (SCOPE does not support other versions) and tells you how to install one if it is missing;
2. creates a private virtual environment in the SCOPE data folder, outside the repository;
3. installs SCOPE, this interface and `cell2mol` in it (internet and `git` are needed, and it takes a few minutes);
4. opens the window.

Later starts take a few seconds. The launcher reinstalls by itself after a `git pull` that changes `core/pyproject.toml`.

| Option | What it does |
|---|---|
| `--reinstall` | Installs again in the private environment, then opens the window |
| `--where` | Prints where the private environment is, and stops |
| `--check` | Builds the window, prints one line and stops (tests the installation) |

> **Note.** `cell2mol` is not on PyPI, so it is installed from the commit named in SCOPE's README. If `git` is missing, the window still opens with a warning, and the SCOPE light shows `cell2mol` as missing until you install `git` and run `--reinstall`.

### When SCOPE is already installed

Start the window with `scope gui`. If PySide6 (the library that draws the window) is missing, the first start creates a private virtual environment, installs PySide6 in it (internet needed, about a minute) and opens the window from there. SCOPE itself is not installed twice: the private environment reads the SCOPE you already have. Later starts reuse it, and it is rebuilt only if SCOPE moves to another Python.

| Option | What it does |
|---|---|
| `scope gui --check` | Builds the window, prints the Python and PySide6 versions, and stops |
| `scope gui --reset-env` | Deletes the private environment |
| `SCOPE_GUI_NO_ENV=1` | Turns the automatic environment off, so you manage PySide6 yourself with `pip install 'scope-qc[gui]'` |

### The SCOPE light

The light under the **SCOPE** title shows whether this window can start SCOPE, with the installed version. The window starts `scope run` in a separate process, so SCOPE must be installed in the same Python.

| Light | Meaning |
|---|---|
| Green | SCOPE is active: it imports, a run can start, and Python is 3.12 |
| Amber | SCOPE runs, but on a Python other than 3.12, which SCOPE does not support |
| Red | SCOPE cannot be started from this Python |

The version is read from the installation each time, so it follows an upgrade. The check runs when the window opens, when you return to it after a few minutes, and when you press **Check again**. Click the light for the details (Python, SCOPE and where it is installed, the `scope` command, `cell2mol`, `rdkit`, the settings folder) and, if something is missing, the installation commands.

## Quick start

1. **Environment.** Choose a project folder, for instance `~/scope_project`, and press **Create local environment**.
2. **Systems.** Press **Import .xyz…** and choose a molecule.
3. **Pipeline.** Press **New input…**, fill in the form and save. Add a second input for the next calculation and list the first one under *Requisites*.
4. **Run.** Choose the system and press **Run**.
5. **Cluster** (optional). Add your cluster, press **Test connection**, then upload, run and download.

## Workspaces

A workspace is one project as this window sees it: an environment, the input files of its pipeline, a cluster connection and a project folder on that cluster. You can keep several and switch between them; the window shows one at a time.

| Part of a workspace | Where you set it |
|---|---|
| Environment (local folders) | 1 · Environment |
| Input files of the pipeline | 3 · Pipeline |
| Cluster connection (a saved profile) | 5 · Cluster, top part. One profile can serve many workspaces. |
| Project folder and environment file on the cluster | 5 · Cluster, *Project on the cluster* |

### Create, switch, rename, delete

The switcher sits under the SCOPE title in the left bar.

- **+** makes a new, empty workspace and opens step 1. It keeps the cluster connection of the workspace you were in and proposes `~/scope_projects/<name>` as its project folder on the cluster.
- Choose a workspace in the list to switch. Everything is saved as you work, so nothing is lost by switching or by closing the window, which reopens on the workspace shown last.
- **⋯** renames or deletes the workspace shown. Deleting removes only the workspace from this window: its environment, systems, input files, runs and everything on the cluster stay as they are. The last workspace cannot be deleted.

### Export, import and shared folders

- **⋯ › Export this workspace…** writes a small file with the workspace (its paths, input list and cluster project) and the connection of its profile. No project file is copied and no password exists to be copied.
- **⋯ › Import a workspace…** reads such a file, for instance on another computer. A workspace name already in use gets *(2)*; a different saved connection with the same name is never replaced (the imported one gets a new name). Paths that do not exist on this computer are listed, so you can open the environment and inputs from where they are.
- If two workspaces use the same project folder on the same cluster, the Cluster page says so. It is allowed, but do not run the same system from both.

### Runs and workspaces

Runs do not belong to the window, so they keep going whichever workspace is shown. When you come back to a workspace, its run is shown again, or how it ended. On the Cluster page, **Watch runs** finds a run of that workspace's project again.

> **Warning.** Two workspaces can point to the same environment. The Run page then refuses to start a system that is already running from that environment, from any workspace or window, because two runs of one system overwrite each other's results.

> **Note.** The first time this version starts, it makes a workspace called *Default* from what the window remembered before: the last environment and, if there was exactly one cluster profile, its project folder. Runs started with an older version are shown there.

## Runs

The **Runs** page (left bar) lists every run of every workspace in one table: the workspace, the system, where it runs, its state and its log.

- Runs on this computer are refreshed every few seconds while the page is shown.
- **Check the clusters** asks every cluster project of your workspaces which runs are active. It only reads, and it is the only moment this page contacts a cluster.
- **Show** (or a double-click) switches to the run's workspace and follows the run: on the Run page for this computer, on the Cluster page for a cluster.
- **Stop the run** stops the selected run, here or on its cluster. Jobs already submitted to a scheduler are not cancelled.

## How SCOPE thinks

SCOPE organises work in a fixed hierarchy: **System → Branch → Workflow → Job → Computation**.

| Term | Meaning |
|---|---|
| **Environment** | Where things are: three folders (sources, systems, computations) and, on a cluster, the scheduler, queues and software modules. Saved as `scope_env_<name>.npy`. |
| **Source** | A structure: a molecule or a crystal cell, normally read from an `.xyz` file. |
| **System** | The container for one chemical entity: its sources and all calculations done on them. Saved as `Systems/<name>/<name>.npy`. |
| **Branch** | A line of work inside a system, a folder in `Computations/<system>/`. The jobs of one pipeline share a branch. |
| **Workflow** | The set of jobs applied to one source. |
| **Job** | One step of the pipeline, such as an optimization (`opt`) or a frequency calculation (`freq`). |
| **Computation** | One real software run with its input, output and status. A job can create several (retries, continuations). |
| **Input file** | A small text file (`.scope`) that tells SCOPE which job to run, with which software and settings. |

SCOPE is **incremental**. Each time you press **Run** it looks at what exists, submits what is ready, skips what is running, registers what has finished, and saves. Run it again and again until everything is done.

# The five steps

## 1 · Environment

The environment tells SCOPE where your files live. It records three folders:

- **Sources**: your structure files, one subfolder per system.
- **Systems**: one subfolder per system, holding its `.npy` file.
- **Computations**: one subfolder per system, holding all inputs and outputs.

### Create a local environment

1. Choose a **project folder**. The three subfolders are filled in for you, and you may edit them.
2. Press **Create local environment**. The environment file is saved in the project folder.

### Open an existing environment

**Open existing environment…** loads one made earlier, for instance on a cluster with `scope config`. If it was created on another computer, its folders may not exist here; the summary lists which ones are missing.

> **Tip.** Names may contain letters, digits, `_`, `-` and `.`, with no spaces.

> **Warning.** Files with the extension `.npy` are Python pickle files. Opening one runs code stored inside it. Open only files you created or trust.

## 2 · Systems

A system is the container for one molecule or crystal and everything calculated on it.

The table lists the systems found in the environment's Systems folder, with the branches that are finished or terminated (SCOPE marks them with small files named `<branch>_FINISHED` and `<branch>_TERMINATED`). Select a row to see its structure below; the first system is shown straight away.

### The structure

The lower half shows the structure SCOPE will compute, as SCOPE holds it in the system file: the atoms, their coordinates and the bonds SCOPE perceived.

- **3D view:** drag to rotate, scroll to zoom, double-click (or **Reset view**) to start again. **Hydrogens** and **Element labels** switch what is drawn.
- **Show:** each source of the system and each of its states. A new system has one state, *initial*; after calculations, the geometries they produced (an optimised structure, for instance) appear here too, so you can compare them.
- **Formula, atoms, charge and spin** are read from the system.
- **2D drawing:** the same atoms and bonds drawn flat, with double bonds and aromatic rings when they can be worked out from the geometry and the charge. No atom is ever added: if the bond orders cannot be worked out (a missing hydrogen, a radical, a metal), every bond is drawn single and a line under the drawing says so. That line is also a useful warning that the structure may not be what you meant.
- **SCOPE details…** shows SCOPE's own text description of the system: sources, branches, folders.

> **Note.** If the system file cannot be read, the window shows the system's `.xyz` file instead, with bonds guessed from distances, and says so.

### Import molecules

Press **Import .xyz…** and choose one or more files. The file name, without `.xyz`, becomes the system name, and the file is copied into `Sources/<name>/`.

> **Warning.** Use only letters, digits, `_`, `-` and `.` in the name. A space in a system name breaks job submission on a cluster.

## 3 · Pipeline

A pipeline is a set of input files. Each file describes **one job**. The table lists the files, and the graph shows how they depend on each other, read from left to right: an arrow **A → B** means that B starts only after A has finished.

### The input form

**New input…** opens a form. The text on the right is the file that will be written, and the line under it says whether SCOPE accepts it.

| Field | Meaning |
|---|---|
| Branch | The folder name for this line of work, for example `demo` |
| Workflow (sources) | Which sources of the system to run: `*` for all, a name, a pattern such as `water*`, or several names separated by commas |
| Job name | `opt`, `freq`, `scf`… |
| Requisites | Jobs that must finish before this one. Empty means *start right away*. A `freq` job after an optimization needs `opt`. |
| Constrains | Jobs that block this one once they are finished. `self` prevents running the same job twice. |
| Software and computation type | Gaussian 16 (`g16`: scf, opt, freq, ts, td, tda) or Quantum ESPRESSO (`qe`: scf, opt, relax, vc-relax, freq) |
| Functional, basis set, processors, queue | Chemistry and resources. The queue is optional; on a cluster it must match one of the environment's queues exactly. |
| Submit | When ticked, the file says `want_submit = True` and SCOPE submits jobs to the scheduler. Unticked by default. |

Other settings go in the tabs below the form, one `key = value` per line. **Edit selected…** reopens a file in the same form; comments in the file are not kept.

> **Warning.** Never list a job's own name under *Requisites*. The job would wait for itself and never start.

### Warnings in the pipeline

Orange warnings mean that SCOPE would accept the file but something looks wrong: a job that requires itself, a requisite that no loaded file defines, two files that define the same job, or a cycle.

## 4 · Run

Choose a system and press **Run**. The log shows what SCOPE does, live. At the end SCOPE prints a *manual attention required* block: read it, because it lists what you should check.

### Start a run

- **Quiet** prints less, **verbose** prints more.
- **Handle errors** lets SCOPE retry some common failures by itself.
- **Stop** asks the run to end. SCOPE continues where it stopped the next time you run.
- If the environment has a scheduler and an input has *Submit* on, **Run** asks for confirmation first, because it sends real jobs and uses computing time.

On a local environment the log says `No Queue Management has been detected in cluster, disabling submission`. This is expected: nothing is submitted and no inputs are written.

Run again later to advance the pipeline.

### Runs continue without the window

A run starts as a separate process and writes its output to a log file. It keeps going if you close the window, if the window crashes, or if you press Ctrl-C in the Terminal where you started the window.

- Closing the window during a run asks whether to leave the run going (the default) or to stop it.
- Opening the window again finds the run, shows its log, and tells you if it ended while the window was closed.
- The logs are in the `gui_runs` folder next to the SCOPE settings (the SCOPE light shows where).

### Running several systems at once

Runs of different systems can go on at the same time, whether they share an environment or not, and from different workspaces.

> **Warning.** Never run the same system twice at once. Each run loads the system file when it starts and saves it when it ends, so the run that finishes last overwrites what the other one registered. Both runs still submit their jobs, but the system file forgets one of them until you run that input again; SCOPE then finds the job by its name in the queue and registers it again. For this reason the Run page refuses to start a system that is already running from the same environment (from any workspace or window), and the cluster launcher refuses a second run of the same system in one project folder.

## 5 · Cluster

Most calculations run on a cluster. SCOPE must be installed on the cluster and runs there. This window starts it over SSH and moves files with `rsync`.

> **Note.** Your SSH setup is used as it is (keys, `~/.ssh/config`, jump hosts). This program never stores a password. Nothing is sent to the cluster until you press a button.

### Before the first test

Three things must exist on the cluster.

1. **SSH works from your Terminal.** `ssh <host>` logs you in, with a key, or with a password or second factor.
2. **SCOPE is installed**, in its own Python 3.12 environment. For example:

```
conda create --name scope python=3.12
conda activate scope
pip install "cell2mol @ git+https://github.com/lcmd-epfl/cell2mol.git@55649ba5f444895846a5d049adcb056c01bb0421"
pip install scope-qc
```

3. **A cluster environment exists.** On the cluster, run `scope config -n cluster`. It asks for the three folders (give it `<project>/Sources`, `<project>/Systems` and `<project>/Computations`, all inside one project folder), detects the scheduler, then asks for the module names of Gaussian 16 and Quantum ESPRESSO (press Enter to skip one) and for the queues. The result is the file `scope_env_cluster.npy`.

The module names you give there are what SCOPE uses to find Gaussian 16 and Quantum ESPRESSO (see *The three lights*).

### Set up a profile

The page has two parts. The **profile** (top) is the connection to one cluster and is shared by all workspaces. The **project on the cluster** (below it) belongs to the workspace shown, so each workspace can use its own folder on the same cluster.

Press **New** (or start typing, the first time), fill in the connection and press **Save profile**. Then fill in the project fields: they are saved with the workspace as you type. The yellow hint under the fields says what is still missing; it turns into a green tick when both parts are complete.

| Field | Part | What to write | Example |
|---|---|---|---|
| Profile name | Profile | Any label: letters, digits, `_`, `-`, no spaces | `nersc` |
| SSH host | Profile | The name you use with `ssh`. The list shows the names found in your `~/.ssh/config`. | `nersc` |
| Path of scope on the cluster | Profile | Where the `scope` program is. Prefer this field. | `~/miniconda3/envs/scope/bin/scope` |
| Line that makes scope available | Profile | Only if the path field is empty, for example `module load scope`. `conda activate` often does not work in this kind of shell, which is why the path is preferred. | |
| Project folder on the cluster | Workspace | The folder that holds `Sources`, `Systems` and `Computations` | `~/scope_projects/water` |
| Cluster environment file | Workspace | The `scope_env_*.npy` made by `scope config` | `~/scope_projects/water/scope_env_cluster.npy` |

> **Tip.** To find the values, log in and run `which scope` (the path of `scope`) and `pwd` inside the project folder. Paths start with `/` or `~/`, with no spaces and no `$VARIABLES`.

### Password or second factor

This window cannot answer a password or code prompt. Press **Show terminal command**, copy the command, run it once in the Terminal app and log in. It opens a connection that stays open for a few hours, and this window reuses it. Keys without a password need no such step.

### Test connection

Press **Test connection**. It only reads: nothing is changed on the cluster. It checks, one by one:

- SSH and the login shell;
- Python on the cluster (SCOPE needs 3.12);
- SCOPE and its version, compared with the version here (a development install reports the same number for different code, so this cannot prove that the code is identical);
- the project folder and the cluster environment file, and that the environment's three folders are the `Sources`, `Systems` and `Computations` inside the project folder;
- the scheduler commands (`sbatch`, `squeue`, `sinfo` for Slurm; `qsub`, `qstat` for SGE);
- the software, as three lights;
- that `TMPDIR` is set (SCOPE's job script needs it).

### The three lights

When the test finishes, three lights show what is available on the cluster, in order of priority: **SCOPE**, **Quantum ESPRESSO**, **Gaussian 16**. They are filled in by the same test, so there is nothing more to press. Point the mouse at a light for the details. The time of the last check is shown at the right.

| Light | Meaning |
|---|---|
| Green | Available. SCOPE imports and the cluster environment loads; or the module loads and the program is found. |
| Amber | Found, but incomplete or doubtful: for instance no MPI launcher for Quantum ESPRESSO, or the check could not finish. Read the details. |
| Red | Not available: SCOPE not found; the module name does not load; or the module loads but the program is not in the path. |
| Grey | Not checked yet, or not set in the cluster environment. |

The check is made by SCOPE itself, on the cluster. For Quantum ESPRESSO it loads the module named in the cluster environment (`module load <name>`), looks for `pw.x`, then for an MPI launcher (`mpirun`, `mpiexec` or `srun`). For Gaussian 16 it loads the module and looks for `g16`. No program is run, no job is submitted and no MPI rank is started.

> **Note.** Software that is installed on the cluster but not named in the cluster environment shows grey, because SCOPE would not use it. Run `scope config` again on the cluster and give the module name.

The lights are a snapshot: they change only when you press **Test connection** again, and the window never contacts the cluster on its own. Before **Run on the cluster**, the window warns you if an input file needs software whose light is red or grey.

### Everyday use

| Button | What it does |
|---|---|
| **Preview upload** | Lists what would be copied. Nothing is copied. |
| **Upload** | Copies the selected system and the input files. Generated calculation files are never uploaded: SCOPE writes them on the cluster. |
| **Run on the cluster** | Starts `scope run` there and shows the log here. SCOPE first runs `scope set_path` so that the paths stored in the system match the cluster folders. You confirm first, and the window says whether the input files will submit jobs. |
| **Watch runs** | Finds a run that is active on the cluster, for example one started before the window was closed, and follows its log. After a passed connection test, the window also tells you if a run is active. |
| **Stop watching** | Stops following. The run goes on. |
| **Stop the run** | Asks the cluster to end the run (the whole run, not only its launcher). Jobs already submitted are not cancelled. |
| **Download results…** | Lists the results of the selected system on the cluster and lets you choose what to bring back (see *Download results*). |

A run started from here is detached: it has its own process and log on the cluster (in `<project>/logs/`), so it keeps going if you close the window, if the window crashes, or if the connection drops. Jobs already handed to the scheduler are never affected by the window. A second run of the same system is refused while one is active.

### Download results

**Download results…** brings the results of a cluster run back into the folders of the workspace shown: the files go to `<Computations>/<system>/`, exactly as they are under `<project>/Computations/<system>/` on the cluster. When a cluster run finishes, the window reminds you of this button.

1. The window lists the cluster folder of the system (read-only) and compares each file with the copy here.
2. It ticks what is **new** or **changed** on the cluster. Heavy working files (wavefunctions, scratch, checkpoints) and files larger than the **size limit** (200 MB unless you change it) are listed but left unticked, so a file of several GB is never copied by accident.
3. Tick or untick freely. **Show only…** filters the list (`*.log`, or a part of a name); **Tick all shown** works on what the filter shows.
4. The line under the table gives how much is ticked, and refuses the download if this computer does not have the space.
5. Press **Download**.

| Status | Meaning | Proposed |
|---|---|---|
| new | Not here yet | Yes, unless heavy or over the limit |
| changed | Different here, and the cluster's copy is newer | Yes, unless heavy or over the limit |
| same | Same size and date | No |
| newer here | Different here, and the local copy is newer | No: it is never replaced unless you tick it |

What makes it safe:

- Files are written only inside this workspace's folders; names that would point elsewhere are refused, and links on the cluster are not followed.
- Nothing local is ever deleted.
- An interrupted download resumes where it stopped when you press **Download** again, and each file is replaced only once it is complete.
- The **system file** (the record of everything SCOPE registered) is proposed when the cluster's is newer. It is first copied next to the local one, and only a complete copy replaces it; the previous file is kept as `<system>.npy.bak-<date>`.

> **Tip.** For very large transfers, **Copy command line** puts the equivalent `rsync` command on the clipboard. Paste it in a Terminal (inside `screen` or `tmux` if you like); it reads the ticked names from a list file and can be run again to resume. The system file is not part of it: replace that from the window, which keeps a backup.

# Reference

## Local vs cluster

| | This computer (no scheduler) | Cluster (Slurm or SGE) |
|---|---|---|
| Create environments, systems, input files | Yes | Yes |
| Draw the pipeline | Yes | Yes |
| Write calculation inputs and job scripts | No | Yes, when *Submit* is on |
| Submit and run calculations | No | Yes |
| Register finished outputs | Yes, if the files are here | Yes |
| Look at results | Yes | Yes |

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

Worth knowing:

- Lines starting with `#` are comments.
- SCOPE turns most values to lower case, so `'6-31G*'` and `'6-31g*'` are the same. Branch names keep their case.
- If `want_submit` is missing, SCOPE assumes **True**. The form always writes it.

> **Warning.** SCOPE checks the software and the computation type, but not the functional or the basis set. A typo shows up only when the calculation fails.

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| The light under SCOPE is red | SCOPE cannot be imported by the Python that runs this window | Click the light, copy the installation commands, install SCOPE in that environment and press **Check again** |
| `scope gui` stops at the first start with a pip error | The private environment could not download PySide6 (no internet, a proxy, or a very new Python without wheels) | Check the connection and run `scope gui` again, or install by hand: `pip install 'scope-qc[gui]'` |
| The window did not appear | On macOS a window started from a Terminal can open behind other apps | Press Cmd+Tab and choose *Python* |
| I closed the window, or it crashed, during a run | Nothing is lost: runs are independent of the window | Open the window again, and on the Cluster page press **Watch runs** |
| A job never starts and SCOPE says `requisites NOT met` | The job lists itself, or a job that never finishes, as a requisite | Edit the input. Requisites are jobs that must finish before this one. |
| `scope run` stops with `EOFError` | An input names a queue that only partly matches (`shor` for `short`), and SCOPE asks a question that cannot be answered here | Use the exact queue name |
| A system name with a space | Job submission splits the name in two | Rename the `.xyz` file, with no spaces |
| The environment shows *folder(s) not found* | The environment was made on another computer | Create a local one, or open the cluster one on the cluster |
| Nothing is written when you run on your own computer | There is no scheduler, so SCOPE does not generate inputs | Use the Cluster step |
| The cluster test fails at SSH | Host unknown, key not loaded, or password or second factor needed | Check `~/.ssh/config`. For a second factor, use **Show terminal command**. |
| A light is grey: *not set* | The cluster environment names no module for that software | On the cluster, run `scope config` again and give the module name |
| A light is red: *module fails* | The module name in the cluster environment is wrong or cannot be loaded | Run `module avail` on the cluster, then correct the name with `scope config` |
| Quantum ESPRESSO is amber: *no MPI launcher* | `pw.x` was found but no `mpirun`, `mpiexec` or `srun` is visible after loading the module | Check the module, or ask the cluster support which launcher to use |
| Profile hint: *Write the path starting with / or ~/* | The path is relative, has spaces or a `$VARIABLE` | Use `/home/you/...` or `~/...` |
| *Input files with the same name* when you upload or run on the cluster | All inputs go into one `inputs` folder on the cluster, so two files called `opt.scope` would replace each other | Rename one of them in step 3 |
| A cluster job fails at once with `TMPDIR: parameter null or not set` | SCOPE's job script needs the variable `TMPDIR` on the compute node | Ask the cluster support, or set it in your shell profile |

## Glossary

| Term | Meaning |
|---|---|
| **Branch, Computation, Environment, Input file, Job, Source, System, Workflow** | See *How SCOPE thinks*. |
| **Queue, partition** | A group of cluster nodes with its own limits. |
| **Scheduler** | The cluster program that decides when jobs run (Slurm or SGE). |
| **Module** | The cluster's way to make a program available, for example `module load gaussian/16`. |
| **Pickle, `.npy` file** | SCOPE's saved objects. Open only trusted ones. |

## About this GUI

This interface calls the same SCOPE functions as the command line (`scope config`, `scope create_single`, `scope run`, `scope set_path`) and starts `scope run` as a separate process. The look follows your system, or the choice made with the sun and moon button at the bottom of the left bar.
