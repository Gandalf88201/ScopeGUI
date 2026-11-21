# Getting started

## Welcome

SCOPE prepares, submits and tracks quantum-chemistry calculations (Gaussian 16 and Quantum ESPRESSO) for molecules and molecular crystals. This window guides you through the work in six steps.

| Step | What you do | What SCOPE needs |
|---|---|---|
| 1 Environment | Say where your files live | Three folders and a name |
| 2 Systems | Bring in the molecules to compute | `.xyz` files |
| 3 Pipeline | Describe what to compute, and in what order | Input files (`.scope`) |
| 4 Run | Let SCOPE act on the pipeline | An environment, a system and input files |
| 5 Cluster | Run on a remote cluster instead of this computer | An SSH connection |
| 6 Results | See what SCOPE computed and registered | A system file with results |

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
3. installs SCOPE, this interface and `cell2mol` in it (internet and `git` are needed, and it takes a few minutes), and SCOPE's add-ons `scope-sco` and `scope-azo` from the same checkout, so that systems saved with them can be opened;
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

### Updates of SCOPE

When SCOPE was installed from a git checkout (as `./scope-gui` does), a second line under the light says whether newer code is on GitHub. Click it for the details.

- **The window asks first.** Until you allow it, the window never contacts GitHub; the line reads *Check for SCOPE updates?*. In the window that opens, tick **Check for updates once a day** to allow it. Closing the window without ticking means no; you can tick it later.
- **Updates come from main.** The check compares your copy with the `main` branch of the GitHub repository your branch follows (the remote it pushes to; `origin` if it follows none), whatever branch you are on: a branch of your own, such as `gui-demo`, is compared with `main`, not with its own copy on GitHub. If the folder also has the original SCOPE repository as a remote, its `main` is listed too, for information only.
- **The check changes nothing.** It runs `git fetch`, which only updates git's record of what GitHub holds. The line then shows *N updates on origin/main* (or *Up to date*), and the window lists the new commits with their date and title. **Check now** asks GitHub at once.
- **Update only when it is safe.** **Update** moves the branch you are on forward to `main` (`git merge --ff-only`). It is offered only when nothing of yours would be touched: no uncommitted changes to SCOPE's files, and no commits of your own that GitHub lacks. Otherwise the window says why and which git command to use.
- **Restart to use the new code.** After an update, **Restart the window** closes it and opens it again; runs keep going. If the update changed SCOPE's installation recipe, start the window with `./scope-gui`, which reinstalls by itself.

| You see | Meaning |
|---|---|
| ↑ *3 updates on origin/main* | `main` on GitHub has newer code than your copy |
| ↻ *Up to date with origin/main* | Nothing new since the last check |
| ! *Update check failed* | GitHub could not be reached (no network, or the repository needs a password); the details say why |
| no line | SCOPE was installed as a package, not from a checkout: update it the way you installed it |

A branch of your own (for instance a development branch that follows no branch on GitHub) is compared with the main branch of the repository; the window tells you how many new commits it has, and you bring them in with git.

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

The **Runs** page (left bar) lists every run of every workspace in one table: the workspace, the system, where it runs, its state, its jobs in the scheduler queue, when it started and its log.

- Runs on this computer are refreshed every few seconds while the page is shown.
- **Refresh** updates the runs on this computer and asks every cluster project of your workspaces which runs are active, how the last run of each system ended, and which of your jobs of that project are in the scheduler queue (`squeue` or `qstat`). It only reads, and it is the only moment this page contacts a cluster. The line under the table says when it last refreshed and what each cluster answered.
- **Clean up…** removes the ended runs of this computer from the list and deletes their logs (in the window's own `gui_runs` folder), after asking. Running runs are kept, results are not touched (they are in the system files), and the rows of the clusters stay: each shows the latest state of a system there, including results not read yet.
- **Show** (or a double-click) switches to the run's workspace and follows the run: on the Run page for this computer, on the Cluster page for a cluster.
- **Stop the run** stops the selected run, here or on its cluster. Jobs already submitted to a scheduler are not cancelled: cancel them on the cluster with `scancel` or `qdel`.

**State and Jobs are two different things.** *State* is about the SCOPE run itself. On a cluster, a SCOPE run submits its jobs to the scheduler and ends, often within a minute, while the jobs can wait in the queue for hours. So:

| State | Meaning |
|---|---|
| running | SCOPE is working now. |
| waiting for jobs | SCOPE has ended, and jobs it submitted are still in the queue. The *Jobs* column says how many are running or pending (hover over it for the job ids). |
| done, results not read yet | (cluster) No job of the system is left in the queue, but files in `Computations/<system>/` were written after SCOPE last saved the system: SCOPE has not read them, so the system file does not hold their results yet. Hover over the state for what to do. |
| finished (exit 0) | SCOPE has ended and, on a cluster, none of the system's jobs is left in the queue. Run again to let SCOPE collect the results and go on with the next jobs. |
| stopped / ended without finishing | SCOPE was stopped, or its process disappeared without writing how it ended. |

**Why results can be "not read yet".** SCOPE reads (registers) the output of a calculation only when it runs, and saves the system file at the end of each run. On a cluster, `scope run` submits the jobs and ends; the jobs write their outputs later. Until SCOPE runs again, the cluster's system file does not contain those results, and neither does a copy of it you download. Two ways to have them read:
- press **Run on the cluster** again (SCOPE reads the outputs and goes on with the next jobs, if any), then **Download results…** with the system file ticked; or
- download the outputs and run the system on this computer (Run page): SCOPE reads them here.

The window notices this by comparing dates: a file in `Computations/<system>/` newer than `Systems/<system>/<system>.npy` was written after SCOPE last saved. A file you touched by hand there counts too.

A job belongs to a system when it runs in the system's folder of the project (`Computations/<system>/…`) or, if the scheduler does not tell the folder, when its name starts with the system name. Folders are also compared with their links resolved, so a project reached through a link (for instance `/home/…` pointing to `/gpfs/home/…`) still finds its jobs.

The queues of Slurm (`squeue`) and SGE (`qstat`, recognised by `qconf` or `$SGE_ROOT`, as SCOPE does; each job's folder is read with `qstat -j`) are read. On another scheduler the Jobs column says *scheduler not recognised*, never *none in queue*. The Jobs column of a cluster row shows the queue as it was at the last check; runs on this computer use no queue (—). The Cluster page does the same when a run it follows ends: it looks at the queue once, and says that jobs are still waiting, or that results are not read yet, instead of offering to download the results.

## How SCOPE thinks

SCOPE organises work in a fixed hierarchy: **System → Branch → Workflow → Job → Computation**. Next to it, the chemistry lives in **System → Source → State**: a workflow is one source inside one branch, and its jobs read and write states of that source.

| Term | Meaning |
|---|---|
| **Environment** | Where things are: three folders (sources, systems, computations) and, on a cluster, the scheduler, queues and software modules. Saved as `scope_env_<name>.npy`. |
| **System** | The container for one chemical entity: its sources and all calculations done on them. Saved as `Systems/<name>/<name>.npy`. |
| **Source** | A structure of the system: a molecule or a crystal cell, normally read from an `.xyz` file. One system can hold several, for instance the high- and the low-spin geometry of one compound. The charge and spin belong to the source. |
| **State** | One geometry and its results inside a source: `initial` when the source is imported, then the states jobs write (an optimised geometry with its energy, frequencies…). States belong to the source, not to a branch. |
| **Branch** | A line of work inside a system, a folder in `Computations/<system>/`. The jobs of one pipeline share a branch. |
| **Workflow** | The set of jobs applied to one source inside one branch. An input file's *workflow* field is a pattern of source names (`*`, `hs*`…) that says which workflows the job goes into. |
| **Job** | One step of the pipeline, such as an optimization (`opt`) or a frequency calculation (`freq`). It reads one state (*istate*) and writes one (*fstate*). |
| **Computation** | One real software run with its input, output and status. A job can create several (retries, continuations). |
| **Input file** | A small text file (`.scope`) that tells SCOPE which job to run, with which software and settings. |

SCOPE is **incremental**. Each time you press **Run** it looks at what exists, submits what is ready, skips what is running, registers what has finished, and saves. Run it again and again until everything is done.

# The six steps

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

The tree lists the systems found in the environment's Systems folder as **System → Source → State**, with the branches that are finished or terminated (SCOPE marks them with small files named `<branch>_FINISHED` and `<branch>_TERMINATED`). Open a system to see its sources, and a source to see its states and what each holds (geometry, energy, frequencies). Select a system to see its structures below; the first system is shown straight away. Select a source (or one of its states) to see and set its charge and spin in the **Source** box.

### The structure

The lower half shows the structure SCOPE will compute, as SCOPE holds it in the system file: the atoms, their coordinates and the bonds SCOPE perceived.

- **3D view:** drag to rotate, scroll to zoom, double-click (or **Reset view**) to start again. The start view shows the molecule spread out as much as possible, turned the same way as the 2D drawing, so the two can be compared atom by atom. **Hydrogens** and **Element labels** switch what is drawn.
- **Show:** each source of the system and each of its states. A new system has one state, *initial*; after calculations, the geometries they produced (an optimised structure, for instance) appear here too, so you can compare them.
- **Formula, atoms, charge and spin** are read from the system.
- **2D drawing:** the same atoms and bonds drawn flat, with double bonds and aromatic rings when they can be worked out from the geometry and the charge. No atom is ever added: if the bond orders cannot be worked out (a missing hydrogen, a radical, a metal), every bond is drawn single and a line under the drawing says so. The drawing keeps its proportions at any size of the window. That line is also a useful warning that the structure may not be what you meant.
- **SCOPE details…** opens SCOPE's own text description of the system (sources, branches, folders) in a separate window that you can resize, scroll and copy from. It stays open while you select other systems and is updated when you press the button again.

> **Note.** If the system file cannot be read, the window shows the system's `.xyz` file instead, with bonds guessed from distances, and says so.

### Import molecules

**Import .xyz…** offers three ways:

- **One new system per file**: each file becomes its own system, named after the file (without `.xyz`).
- **One new system with these files as its sources**: you name the system, and each file becomes one of its sources (for instance `fe_hs.xyz` and `fe_ls.xyz` for the two spin states of one compound). This is the usual case when the structures belong together.
- **Add files as sources of the selected system**: the files become new sources of a system that already exists. You confirm the name of each source (dots in the file name are kept). Refused while a run of that system is active on this computer; the previous system file is kept as `<system>.npy.bak-<time>`.

Every file is copied into `Sources/<system>/`.

### Charge and spin

An `.xyz` file has neither, so an imported source starts with every atom at charge 0 and spin 0. That is SCOPE's **import default**: the Source box says so in amber, and the Run page warns before running a source whose values were never checked. A radical with the default spin 0 is shown in red: its electron count cannot have 2S = 0.

- **Total charge** and **Total spin (2S)**: what every calculation of the source uses (Gaussian writes them as charge and multiplicity 2S + 1). They are the **sums of the atoms' values**, as SCOPE stores them. **Save totals** sets every atom to 0 and puts the whole charge and spin on one atom (the first metal, else the first atom), which avoids SCOPE's own behaviour of adding to whatever atom 1 already had. **Confirm as they are** marks the current values as checked.
- **Atoms…** lists every atom with its charge, its spin and the atoms it is bonded to, and lets you set them one by one (for instance the spin on each metal centre, which Quantum ESPRESSO uses to start the magnetisation). The totals update as you type.
- **Connectivity…** shows SCOPE's adjacency matrix: a 1 where two atoms are bonded.
- The spin must agree with the number of electrons (an even count needs an even 2S); a value that does not is refused. Quantum ESPRESSO inputs need a neutral state: the Run page warns otherwise.

> **Note.** Changes are saved into this computer's system file. If the system also runs on a cluster, upload it before the next cluster run, and do not download the cluster's system file over it afterwards.

> **Warning.** Use only letters, digits, `_`, `-` and `.` in the name. A space in a system name breaks job submission on a cluster.

## 3 · Pipeline

A pipeline is a set of input files. Each file describes **one job**. The table lists the files with the state each job reads and writes, and the graph draws them as SCOPE's manuscript does, from left to right: jobs are boxes, **states** are pills between them. A state → job arrow means the job starts from that geometry; a job → state arrow means it writes that state; a dashed arrow back to a state means the job adds its results to the state it read (frequencies on the optimised geometry). A dotted grey arrow **A → B** is a requisite: B starts only after A has finished.

A job is identified by **branch, workflow and job name**: an `opt` job for the `hs*` sources and one for the `ls*` sources are two different jobs, not a duplicate. Choose a system in **Check against system** to match the workflow patterns against its real sources.

### The input form

**New input…** opens a form. The text on the right is the file that will be written, and the line under it says whether SCOPE accepts it.

| Field | Meaning |
|---|---|
| Branch | The folder name for this line of work, for example `demo` |
| Workflow (sources) | Which sources of the system to run: `*` for all, a name, a pattern such as `water*`, or several names separated by commas |
| Job name | `opt`, `freq`, `scf`… |
| Requisites (when) | Jobs that must finish before this one. Empty means *start right away*. A `freq` job after an optimization needs `opt`. Requisites decide only **when** the job starts, never which geometry it uses. |
| Initial state (istate) | The state the job starts from. `initial` is the imported structure. To start from the result of an earlier job, give the state that job writes: for `freq` after `opt`, `opt`. When you type a requisite, the form fills it in for you. |
| Final state (fstate) | The state the job writes. SCOPE's default is the job name. The form proposes it for jobs that make a new geometry (opt, ts, relax), and the initial state for the others (freq, scf, td), so their results sit on the geometry they used. |
| Constrains | Jobs that block this one once they are finished. `self` prevents running the same job twice. |
| Software and computation type | Gaussian 16 (`g16`: scf, opt, freq, ts, td, tda) or Quantum ESPRESSO (`qe`: scf, opt, relax, vc-relax, freq) |
| Functional, basis set, processors, queue | Chemistry and resources. The queue is optional; on a cluster it must match one of the environment's queues exactly. |
| Submit | When ticked, the file says `want_submit = True` and SCOPE submits jobs to the scheduler. Unticked by default. |

Other settings go in the tabs below the form, one `key = value` per line. **Edit selected…** (or a double-click on a job in the graph) reopens a file in the same form; comments in the file are not kept.

### Add a job after another one

The easiest way to build a sequence: select a job in the table and press **Add job after selected…**, or right-click its box in the graph and choose **Add a job after…**. The form opens already filled in for a job that waits for that one and starts from its result:

- the same branch and sources (a job only waits for jobs of its own branch and source);
- *Requisites* = that job, and *Initial state* = the state it writes, so the new job uses its geometry;
- the same software, method, extra settings (the *&qc_data*, *&environment* and *&options* tabs), processors, queue and submission choice;
- a job type that usually comes next (*freq* after a geometry job, else *scf*) and a name the branch does not use yet.

Check everything, in particular the queue and *Submit*, and press **Save**: nothing is saved before, and nothing runs until you press Run. Settings of the *&job_data* tab (for instance `job_setup = 'rep_opt'`) are not copied, since they describe the first job only.

### Connect jobs you already have

- **Drag** from one job's box onto another's in the graph: the second job waits for the first and starts from its result. A window lists the settings that change in the second job's file (`~` changed, `+` added); nothing is written until you press **Save the change**.
- **Several jobs in a row:** select them in the table (Cmd/Ctrl- or Shift-click) and press **Chain selected…**. Put them in order by dragging them in the list (the proposal keeps the order they already have, otherwise the table's order); each job will wait for the one above it and start from its result. The preview shows every file that changes; **Save the changes** writes them all.
- **One job after several** (for instance a single point that needs two optimisations): drag each of them onto it. A job reads one state, so it keeps starting from the first one's result; the others only decide when it starts.

What is linked follows SCOPE's rules: both jobs in the same branch, on sources that meet, no job waiting for itself, no cycle. A link that breaks them is refused with the reason. A job that writes its results into a state without a geometry (an `scf` writing `sp`) passes on the geometry it used, so the next job never starts from a state without coordinates; a `freq` job still writing SCOPE's default state writes onto the geometry it starts from, so energy and frequencies sit on one state. The file is written again from its settings: comments in it are not kept.

> **Warning.** Never list a job's own name under *Requisites*. The job would wait for itself and never start.

### Warnings in the pipeline

Orange warnings mean that SCOPE would accept the file but something looks wrong: a job that requires itself, a requisite that no loaded file defines for the same sources, two files that define the same job for the same sources, a cycle, a state name written as a requisite (requisites are job names), a requisite that is a job of another branch or of other sources (SCOPE only waits for jobs of the same branch and source), a job that waits for another one but still reads a different state (typically `freq` after `opt` reading `initial`), a state no loaded job writes, or two branches that write the same state of the same sources (states belong to the source, so one would overwrite the other).

## 4 · Run here

Choose a system and press **Run**. The log shows what SCOPE does, live.

**Review before running.** Above the log, a table lists every input file as it will run: the job, its branch and sources, software and type, the state it reads and the one it writes, what it waits for, processors, queue, and whether it submits jobs. The **Check** column says ✓ *ready*, ! *to look at* (a warning of the Pipeline page) or ✗ *will not run as meant* (a file SCOPE does not accept, or a queue the environment does not have); hover over it for every message. The **Cluster** page shows the same table for the cluster: its queues and scheduler are known after **Test connection**, and missing software found by the test is listed too. **Review…** on the Pipeline page opens it on its own. At the end SCOPE prints a *manual attention required* block: read it, because it lists what you should check.

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

> **Note.** Your SSH setup is used as it is (keys, `~/.ssh/config`, jump hosts). This program never stores a password: when the cluster asks for one, you type it in a window, it goes to the cluster and is forgotten. Nothing is sent to the cluster until you press a button.

### Before the first test

Three things must exist on the cluster.

1. **You can log in over SSH.** `ssh <host>` works from your Terminal, with a key, or with a password or second factor. This window can do the same login for you (see *Connect*).
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

The page has three cards, in the order you use them. **1 · Cluster** is the profile: the connection to one cluster, shared by all workspaces. Once it is saved and complete it takes one line (who, where, where `scope` is) with **Connect…**, **Disconnect** and **Test connection**; **Edit…** shows its fields (host, user, port, path of `scope`, **Save profile**), and a new or incomplete profile shows them by itself. The three lights and, after a test, **Details of the last test** are in this card too (the details open by themselves when something needs a look). **2 · Project on the cluster** belongs to the workspace shown, so each workspace can use its own folder on the same cluster. **3 · Transfer and run** has the buttons of everyday use and the log.

Press **New** (or start typing, the first time), fill in the connection and press **Save profile**. If the cluster needs a password, press **Connect…** now. Then fill in the project fields: they are saved with the workspace as you type. The yellow hint under the fields says what is still missing; it turns into a green tick when both parts are complete.

| Field | Part | What to write | Example |
|---|---|---|---|
| Profile name | Profile | Any label: letters, digits, `_`, `-`, no spaces | `nersc` |
| SSH host | Profile | The machine you log in to, or an alias from your `~/.ssh/config` (the list shows them). You can also paste the whole command you use in the Terminal: when you leave the field, the user name and the port move to their own fields. | `login.cluster.org` |
| User | Profile | Your login name on the cluster. Leave empty if `~/.ssh/config` already gives it, or if it is the same as on this computer. | `jsmith` |
| Port | Profile | The SSH port. Leave empty for the usual 22 (or the one in `~/.ssh/config`). Some clusters use another one. | `2122` |
| Path of scope on the cluster | Profile | Where the `scope` program is. Prefer this field. | `~/miniconda3/envs/scope/bin/scope` |
| Line that makes scope available (under *Advanced*) | Profile | Only if the path field is empty, for example `module load scope`. `conda activate` often does not work in this kind of shell, which is why the path is preferred. | |
| Project folder on the cluster | Workspace | The folder that holds `Sources`, `Systems` and `Computations` | `~/scope_projects/water` |
| Cluster environment file | Workspace | The `scope_env_*.npy` made by `scope config` | `~/scope_projects/water/scope_env_cluster.npy` |

> **Example.** If you log in with `ssh -p 2122 jsmith@login.cluster.org`, paste exactly that into **SSH host**: it becomes host `login.cluster.org`, user `jsmith`, port `2122`. `jsmith@login.cluster.org:2122` works too. Every command this window runs, and every file it copies, then uses that port and that user.

> **Tip.** To find the values, log in and run `which scope` (the path of `scope`) and `pwd` inside the project folder. Paths start with `/` or `~/`, with no spaces and no `$VARIABLES`.

### Connect

Press **Connect…**. This window logs in the way your Terminal does, and shows what the cluster asks:

- **A password or a verification code** appears in a small window, with what the cluster said just before (for example *Permission denied, please try again.*). The text is hidden while you type; tick *Show what I type* to see it. A cluster that asks for a password and then a code (a second factor) opens the window twice.
- **The first time you log in to a cluster**, ssh asks whether to trust it. The window shows the key fingerprint. Press **Yes** only if it is the one your cluster support gives.
- **Cancel** stops the login and nothing is connected.

Nothing you type is saved: it is passed to ssh and forgotten, never written to a file, a log or the profile. When the login works, the connection stays open for 4 hours, the badge at the top right of the card says **Connected to** and the host name, and every button on the page (test, upload, run, download) reuses it without asking again. **Disconnect** closes it; a run already started on the cluster keeps going. When the 4 hours pass, or the cluster closes the connection, the badge turns to *Not connected* and the next button that needs the cluster tells you to press **Connect…** again. A key without a password needs no such step: the badge may stay *Not connected* and the buttons still work.

If you prefer to type the password in the Terminal, press **Terminal command…** (under **Edit…**), copy the command (it already contains the port and the user of the profile), run it once in the Terminal app and log in. The window reuses that connection too.

**On Windows.** The `ssh` that comes with Windows cannot keep a shared connection open, and the window cannot relay a password there, so every command logs in on its own with a **key**. The button is **Set up key login…**: it opens a console window that creates a key if you have none (press Enter twice for no passphrase: the window needs a key it can use without asking) and adds it to `~/.ssh/authorized_keys` on the cluster. You type the cluster password there, once, and the window never sees it. Then press **Test connection**. **Commands to do it yourself…** shows the same two commands for PowerShell. If the cluster does not accept keys, Windows cannot reach it from this window; use WSL or a Mac or Linux computer. Windows has no `rsync` either: files are then copied with `tar` through `ssh` (both come with Windows 10 and 11), whole files at a time, with their dates kept and nothing deleted.

### Test connection

Press **Test connection**. It only reads: nothing is changed on the cluster. It checks, one by one:

- SSH and the login shell;
- Python on the cluster (SCOPE needs 3.12);
- SCOPE and its version, compared with this computer: when both come from a git checkout the commits are compared, so a different copy of the code is flagged even when the version number is the same (otherwise only the version numbers are compared);
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
| **Upload** | Copies the selected system and the input files. It first compares both sides: it warns when the cluster's system file is newer than this computer's (uploading would replace it), and offers to copy the calculation files (inputs and outputs) that are only here, because the system file alone is not enough. |
| **Run on the cluster** | Starts `scope run` there and shows the log here. SCOPE first runs `scope set_path` so that the paths stored in the system match the cluster folders. You confirm first, and the window says whether the input files will submit jobs. Run does not copy anything: if the system file (`Systems/<system>/<system>.npy`) or an input file is not on the cluster yet, nothing starts and the status line says to press **Upload** first. It also checks that the cluster environment file belongs to the project folder: SCOPE reads systems from the environment's *Systems* folder, so an environment made for another folder (for instance one shared by two workspaces with different project folders) would never find what Upload copied. Each project folder needs its own environment, created there with `scope config`. |
| **Watch runs** | Finds a run that is active on the cluster, for example one started before the window was closed, and follows its log. After a passed connection test, the window also tells you if a run is active. |
| **Stop the run** | Asks the cluster to end the run (the whole run, not only its launcher). Jobs already submitted are not cancelled. |
| **Download results…** | Lists the results of the selected system on the cluster and lets you choose what to bring back (see *Download results*). |

**Synchronisation.** The input and output files in `Computations/<system>/` are the source of truth: the system file only records what SCOPE read from them, and SCOPE reading the same files (same version, same inputs) registers the same results again. So a system can be worked on in several places as long as those files are kept in step, and copying the `.npy` alone is not enough. Different branches, or different workflows (sources), can run on different clusters. Jobs of one workflow should run in one place: later jobs read the states earlier ones write. **Upload** and **Download results…** warn when the two sides differ.

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

If files on the cluster are newer than the cluster's system file, the line under the table says so: SCOPE has not read them yet, so the cluster's system file does not hold their results (see *Why results can be "not read yet"* under Runs).

What makes it safe:

- Files are written only inside this workspace's folders; names that would point elsewhere are refused, and links on the cluster are not followed.
- Nothing local is ever deleted.
- An interrupted download resumes where it stopped when you press **Download** again, and each file is replaced only once it is complete.
- The **system file** (the record of everything SCOPE registered) is proposed when the cluster's is newer. It is first copied next to the local one, and only a complete copy replaces it; the previous file is kept as `<system>.npy.bak-<date>`.

> **Tip.** For very large transfers, **Copy command line** puts the equivalent `rsync` command on the clipboard. Paste it in a Terminal (inside `screen` or `tmux` if you like); it reads the ticked names from a list file and can be run again to resume. The system file is not part of it: replace that from the window, which keeps a backup.

## 6 · Results

This page shows what SCOPE computed and registered for the systems of the workspace: energies, minima, and every calculation with its status and its output file. It only reads: it never saves a system file and never creates a folder, so looking at results cannot change your project.

Choose a system on the left. The page reads its system file (`Systems/<system>/<system>.npy`) in the background and shows:

| Part | What it shows |
|---|---|
| Top line | The system file, its date and size, the SCOPE version that saved it and the one reading it, and the environment whose folders are used |
| Notes | Anything to know before trusting the numbers (see below) |
| **Overview** | One row per state of each source: energy (Hartree), ΔE, whether it is a minimum, imaginary frequencies, the calculations that wrote it, and the status of the last one |
| **Calculations** | Every calculation, by branch and workflow: status, what it read and wrote, wall and CPU time, and whether its output is on this computer. Double-click one to read its output |
| **State** | One state in detail: its spectrum, its frequencies and its structure. Double-click a row of the Overview to open it here |
| **Thermochemistry** | G(T) of a state, or ΔG(T), ΔH and −TΔS between two states, and the temperature where ΔG changes sign |
| **Compare** | The states of several systems of the workspace side by side, by electronic energy or by G(T) |

**Where the files are.** The system file stores the folders where SCOPE ran, for instance on the cluster. The page points them at this workspace's folders (*Sources*, *Systems*, *Computations* of the environment) while it reads, without changing the file. A note says so when the file came from another computer or folder. The same is done by the notebook entry point, so a notebook and this page always show the same data:

```
from scope.gui.results import open_system
system, prov = open_system("/path/to/scope_env_<name>.npy", "water")
```

**Notes you may see.**

| Note | Meaning |
|---|---|
| *N outputs not read yet* | These outputs are on this computer, but SCOPE has not read them, so their energies and frequencies are not in the system file (rows marked ◌). Outputs computed on the cluster: press **Read on the cluster…** (it opens the Cluster page with this system and starts Run there, after you confirm; SCOPE reads the outputs and finished jobs are not submitted again), then **Download from the cluster…** with the system file. Outputs computed here: run the system on the Run here page |
| *N output file(s) are not on this computer* | SCOPE registered (or expects) these outputs, but they are not here: still running, not downloaded, or not started. Energies and frequencies are in the system file and are shown anyway; reading an output needs the file. **Download missing outputs (N)…** opens the download of the Cluster page with exactly those files ticked. Without missing outputs the button reads **Download from the cluster…** and opens the same download with the usual choice: the outputs on the cluster and its system file when it is newer, which is how results computed there reach this computer. It is enabled whenever the workspace has a cluster project |
| *Saved by SCOPE x, read by y* | The file comes from another SCOPE version. Values are read as stored |
| *Newer RDKit* | The system file holds molecules written by a newer RDKit than this one. They are read, and RDKit's warnings (two lines per molecule in the terminal) are counted into this one note. Energies and frequencies are SCOPE's own numbers and are not affected |
| *Older copies kept by downloads* | Each download that replaced the system file kept the previous one as `<system>.npy.bak-<date>`. **Older copies** opens one beside the current file (see below) |
| *A run of … is going on* | A run of this system is active; the page reloads when it saves the system file |

The page reloads by itself whenever the system file changes, for instance at the end of a run or a download. **Reload** reads it again at once.

**Status of a calculation.**

| Shown | SCOPE's status | Meaning |
|---|---|---|
| ✓ finished and converged | `worked` | SCOPE extracted results, the program finished normally and it converged |
| ✓ finished (no new geometry) | `no_coord` | Finished normally; a single point produces no new geometry, so this is the usual result of an `scf` job |
| ◐ results extracted, run not finished | `worked` | SCOPE could read results (for instance the last geometry), but the program did not end normally. The values are provisional |
| ≈ finished, not converged | `worked` | The program ended, but the SCF or the optimisation did not converge (or, for a repeated optimisation, its convergence criteria are not met yet) |
| ! stopped by the time limit | `time_stopped` | SCOPE continues it in a new run (r2, r3…) |
| ✗ SCF did not converge, aborted | `no_scf_convergence`, `aborted` | Failed. With `-e`, SCOPE resubmits common failures by itself |
| ◌ output here, not registered yet | — | The output is here but SCOPE has not read it: run the system again (Run page) to register it |
| … no output here | — | Still running, not downloaded, or not started |
| ? unknown | anything else | A status this window does not know |

SCOPE's status `worked` only means that results could be extracted; the window also uses SCOPE's *finished* and *converged* flags, so green means all three. The Calculations CSV has *finished* and *converged* columns. In the Overview the status is that of the **last** calculation of the state, whose values the state holds; *(after a retry)* means an earlier one stopped or failed and was continued. Labels follow SCOPE's file names: `opt r2` is the second run of job `opt`, and `vc s3 r2` the second run of step 3 of a repeated job.

**ΔE.** Energies are compared only between states with the same formula, the same **charge** and the same **method**: every input setting that changes an energy. For Gaussian: functional, basis, dispersion correction, unrestricted, integration grid. For Quantum ESPRESSO: functional, pseudopotential library (`pp_library`), Hubbard U, dispersion correction. The Method column shows them all. The spin is not part of it, so the high- and low-spin states of one compound are compared. ΔE is measured from the lowest of them, in the units you choose. A state with nothing comparable has no ΔE.

> **Note.** A system saved with an add-on (for instance spin crossover, `scope-sco`) needs that add-on to be opened. The launcher installs the add-ons of the checkout; if one is missing, the page says which and gives the install command.

**The State tab.** Choose a state at the top; the line under it gives its energy, method, number of frequencies (imaginary ones in red) and excited states, and the calculations that wrote it. Three sub-tabs:

| Sub-tab | What it shows |
|---|---|
| **Spectrum** | IR, vibrational density of states (VDOS) or absorption (UV-vis), whichever this state has. Choose the broadening kernel (gaussian, lorentzian, laplacian), its width (cm⁻¹ for IR and VDOS, eV for absorption) and the range. The curves are computed by SCOPE's own functions (`get_ir_spectrum`, `get_vdos_spectrum`, `get_abs_spectrum`), so they are the ones its `plot_*` functions draw with the same settings. Red lines mark the modes or excited states under the curve. **Save plot…** writes PNG, SVG or PDF |
| **Frequencies** | Every mode: frequency, IR intensity, reduced mass, symmetry. A negative frequency is imaginary (red): a minimum has none, a transition state exactly one. **Copy frequencies (CSV)** |
| **Structure** | The geometry of the state with the bonds SCOPE perceived, in 3D and 2D. **Save geometry (.xyz)…** writes it wherever you choose |

A state with no frequencies and no excited states (an `initial` state, a single point) shows its structure. Spectra are computed in memory: nothing is written to the project.

**Zoom on any plot.** Drag across a plot to zoom into that region. A mostly horizontal drag zooms the x axis and fits the y axis to what is visible, which is the quickest way to look at one band of a spectrum. A rectangle zooms both axes. Double-click on the plot, or press **Reset view**, to see everything again. The zoom stays when you change the settings of the same plot (a broader width, another model), and **Save plot…** saves what is shown, zoom included. The line above the plot shows the value under the mouse.

**The Thermochemistry tab.** It lists the states that have frequencies (a frequency job wrote them) and an energy. Choose a state, and optionally a second one to subtract.

| Setting | Meaning |
|---|---|
| T from, to, step | The temperature range of the plot (K) |
| Report at | The temperature whose values are written under the plot (298.15 K by default) |
| Model | `HO` (harmonic oscillator) or `QRRHO` (Grimme's quasi-rigid-rotor model for low frequencies, with its cutoff) |
| Imaginary | What to do with imaginary frequencies: `ignore` (left out, usual for a transition state), `absolute` (taken as real, a diagnostic) or `raise` (stop: the state should be a minimum) |

With one state the plot shows G − H<sub>elec</sub>, H<sub>vib</sub> and −T·S against temperature, and the line under it gives G at the chosen temperature. With two states (A minus B) it shows ΔG, ΔH and −TΔS. Where ΔG crosses zero the two states are equally stable: for the high- and low-spin states of a spin-crossover compound this is T½. If ΔG keeps its sign, the page says which state is the more stable throughout.

The numbers are SCOPE's own (`state.get_thermal_data`), per formula unit (cells: divided by Z). A molecule is one formula unit (Z = 1). A cell's Z comes from its state or, for a state without atoms (a frequency job that writes a new state stores the modes but not the coordinates), from another state of the same source; the IR and VDOS spectra use the same Z. Translational and rotational terms are not included, as in SCOPE. The calculation runs on a copy of the state, so nothing in the system changes. **Copy data (CSV)** and **Save plot…** export what is shown.

> **Note.** Subtracting two states of different formula or method is allowed but warned about: their ΔG has no meaning.

**The Compare tab.** Tick the systems to compare (the one shown is ticked), choose *Electronic energy* or *Gibbs energy G(T)* (with its temperature, model and imaginary policy) and press **Compare**. Other systems are read in the background, read-only, and kept until their file changes. Δ is measured from the lowest value among the states with the same formula, charge and method, across all the systems ticked; states with nothing comparable are listed without Δ. Select a row to plot its group as bars. **Copy table (CSV)** and **Save plot…** export it.

> **Note.** The method shown is the one SCOPE's input asked for (software, functional, basis). If an output was produced with other settings than its input file says, the page cannot tell.

**Export.** **Export → Copy table (CSV)** puts the table of the current tab on the clipboard; **Save table as CSV…** writes it where you choose. On the State tab this is the spectrum shown (curve and sticks) or the frequencies, whichever sub-tab is open. Every CSV starts with comment lines (`# …`) that say where its numbers come from: the system file with its date and size, the SCOPE version that saved it and the one reading it, the environment whose folders were used, the export time, and the settings (units, model, temperatures, spectrum width…). Plots saved with **Save plot…** carry the same text inside the file: the *Description* of a PNG or SVG, the *Subject* of a PDF. **Show folder** opens the system's *Computations* folder.

**Older copies.** When a download replaces the system file, the previous one is kept as `<system>.npy.bak-<date>`. **Older copies (N)** lists them; choose one to see it beside the current file: one row per state with its energy, status and number of runs then and now, and what changed (*computed since*, *energy changed*, *status changed*, *more runs*, *new state*, *not in the current file*). Tick *Only states that changed* to hide the rest. The copy is read like the current file, read-only, and the page keeps showing the current file.

**Notebooks.** **Open in notebook** writes a new Jupyter notebook for the system shown and opens it in Jupyter Lab, in your browser. The notebook:

- opens the system with `open_system`, the same entry point as this page, so it shows the same data, and prints where it comes from and which Python runs it;
- follows Tutorials 3 and 4: sources and states, energies and ΔE, frequencies and the IR spectrum (and absorption, if there are excited states), thermochemistry, and ΔG(T) between two comparable states with the temperature where it changes sign;
- starts from the state shown in the State tab and the two states of the Thermochemistry tab; with nothing chosen, it takes the first suitable ones itself, so it runs on any system, even one with nothing computed yet;
- never calls `system.save()`: the analyses change the system in memory only.

| Question | Answer |
|---|---|
| Where are notebooks written? | In `<project>/Notebooks/`, next to *Sources*, *Systems* and *Computations*. Uploads and downloads never touch this folder |
| Will my edits be overwritten? | No. A notebook is written once; the next one is `<system>-2.ipynb`, then `-3`, and so on |
| Which Python runs it? | The Python of this window, so the same SCOPE and add-ons. **Open in notebook** registers a Jupyter kernel called *SCOPE GUI (Python 3.x)* for that Python (in your Jupyter folder, on macOS `~/Library/Jupyter/kernels/scope-gui`), and the notebook asks for it by name. So another Jupyter (one started with `jupyter lab` in a terminal, VS Code, Anaconda) also runs it with SCOPE. The first cell says which Python runs it |
| One Jupyter or many? | One per window. A second notebook opens in the Jupyter Lab that is already running |
| What happens when I close the window? | If Jupyter Lab started from this window is still running, you choose: **Stop it and close** (save your notebooks in the browser first) or **Keep it running** |
| I use VS Code or another editor | Use the arrow of **Open in notebook → Copy code**: the first cell, which opens the system as this page does, goes to the clipboard |
| And an older copy? | **Open this copy in a notebook**, in the older-copy view, writes and opens a notebook that reads that copy instead of the current file |
| I clicked twice and nothing opened yet | Jupyter Lab takes a few seconds to start the first time; notebooks written meanwhile open as soon as it is up |

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
| The cluster test fails at SSH, with *Permission denied* | A password or second factor is needed, or the connection expired | Press **Connect…** and answer in the window. Check the user and the port. |
| A light is grey: *not set* | The cluster environment names no module for that software | On the cluster, run `scope config` again and give the module name |
| A light is red: *module fails* | The module name in the cluster environment is wrong or cannot be loaded | Run `module avail` on the cluster, then correct the name with `scope config` |
| Quantum ESPRESSO is amber: *no MPI launcher* | `pw.x` was found but no `mpirun`, `mpiexec` or `srun` is visible after loading the module | Check the module, or ask the cluster support which launcher to use |
| Profile hint: *Write the path starting with / or ~/* | The path is relative, has spaces or a `$VARIABLE` | Use `/home/you/...` or `~/...` |
| *Input files with the same name* when you upload or run on the cluster | All inputs go into one `inputs` folder on the cluster, so two files called `opt.scope` would replace each other | Rename one of them in step 3 |
| Results: *was saved with the SCOPE add-on …, which is not installed here* | The system file uses classes of an add-on (for instance spin crossover) | Run the install command shown, or `./scope-gui --reinstall` |
| Results: no Spectrum for a state | No frequency or TD-DFT calculation wrote this state | Look at the state written by the `freq` (or `td`) job |
| Results: the IR spectrum is flat | The output gave no IR intensities (all zero) | Expected for some methods; the Frequencies sub-tab still lists the modes |
| Results: a state is missing from the Thermochemistry list | It has no frequencies or no energy | Run a frequency job on it |
| Results: *the 'raise' policy stops at an imaginary frequency* | The state has an imaginary frequency (a transition state, or a geometry that is not a minimum) | Choose *ignore*, or re-optimise the geometry |
| Results: no ΔE for a state | No other state has the same formula, charge and method (every energy setting), so the energies cannot be compared | Expected, or check the Method column for a setting that differs |
| Results: *Jupyter Lab is not installed in this window's Python* | The notebook was written, but Jupyter Lab is missing | Run the install command shown, or open the notebook in VS Code |
| Results: the notebook does not open in the browser | Jupyter Lab is starting, or failed to | Wait a few seconds; its messages are in `Notebooks/.jupyter-scope-gui.log` |
| Notebook: *this kernel is not the Python of the SCOPE window* | Jupyter chose another kernel | In Jupyter, *Kernel → Change kernel* and choose *SCOPE GUI*, or open the notebook from the window again |
| Notebook: *This kernel runs … which does not have SCOPE* | The notebook runs in another Python, for instance a Jupyter started from a terminal, whose *Python 3* kernel is not the GUI's | *Kernel → Change kernel → SCOPE GUI*. Notebooks written before the SCOPE GUI kernel existed ask for *Python 3*; change it once and save |
| A cluster job fails at once with `TMPDIR: parameter null or not set` | SCOPE's job script needs the variable `TMPDIR` on the compute node | Ask the cluster support, or set it in your shell profile |

## Glossary

| Term | Meaning |
|---|---|
| **Branch, Computation, Environment, Input file, Job, Source, System, Workflow** | See *How SCOPE thinks*. |
| **Queue, partition** | A group of cluster nodes with its own limits. |
| **Scheduler** | The cluster program that decides when jobs run (Slurm or SGE). |
| **Module** | The cluster's way to make a program available, for example `module load gaussian/16`. |
| **Pickle, `.npy` file** | SCOPE's saved objects. Open only trusted ones. |
| **State** | A snapshot of a source: `initial` when it is imported, then one per calculation result (for instance `pbe_opt`). Calculations read one state and write another. |
| **Run (r1, r2…)** | One attempt of a job. r2 continues r1 when it stopped or failed. |
| **Notebook** | A Jupyter file (`.ipynb`) with code and its results. The Results page writes them in `<project>/Notebooks/`; they are yours to edit. |
| **Provenance** | Where a number comes from: the system file, its date, the SCOPE versions and the settings. Exports start with it. |

## About this GUI

This interface calls the same SCOPE functions as the command line (`scope config`, `scope create_single`, `scope run`, `scope set_path`) and starts `scope run` as a separate process. The look follows your system, or the choice made with the sun and moon button at the bottom of the left bar.
