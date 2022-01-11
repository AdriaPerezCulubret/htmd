# (c) 2015-2022 Acellera Ltd http://www.acellera.com
# All Rights Reserved
# Distributed under HTMD Software License Agreement
# No redistribution in whole or part
#
from __future__ import print_function


from htmd.home import home
import numpy as np
import os
from os.path import join
from glob import glob
from moleculekit.util import _missingSegID, sequenceID
import shutil
from htmd.builder.builder import (
    detectDisulfideBonds,
    detectCisPeptideBonds,
    convertDisulfide,
    _checkMixedSegment,
    BuildError,
    UnknownResidueError,
    MissingAngleError,
    MissingBondError,
    MissingParameterError,
    MissingTorsionError,
    MissingAtomTypeError,
)
from subprocess import call
from moleculekit.molecule import Molecule
from htmd.builder.ionize import ionize as ionizef, ionizePlace
from htmd.util import ensurelist
import unittest

import logging

logger = logging.getLogger(__name__)


def _findTeLeap():
    teleap = shutil.which("teLeap", mode=os.X_OK)
    if not teleap:
        raise FileNotFoundError(
            "teLeap not found. You should have AmberTools installed "
            "(to install AmberTools do: conda install ambertools -c conda-forge)"
        )
    if os.path.islink(teleap):
        if os.path.isabs(os.readlink(teleap)):
            teleap = os.readlink(teleap)
        else:
            teleap = os.path.join(os.path.dirname(teleap), os.readlink(teleap))
    return teleap


def defaultAmberHome(teleap=None):
    """Returns the default AMBERHOME as defined by the location of teLeap binary

    Parameters:
    -----------
    teleap : str
        Path to teLeap executable used to build the system for AMBER
    """
    if teleap is None:
        teleap = _findTeLeap()
    else:
        if shutil.which(teleap) is None:
            raise NameError(f"Could not find executable: `{teleap}` in the PATH.")

    return os.path.normpath(os.path.join(os.path.dirname(teleap), "../"))


_defaultAmberSearchPaths = {
    "ff": join("dat", "leap", "cmd"),
    "topo": join("dat", "leap", "prep"),
    "param": join("dat", "leap", "parm"),
    "lib": join("dat", "leap", "lib"),
}


def htmdAmberHome():
    """Returns the location of the AMBER files distributed with HTMD"""

    return os.path.abspath(os.path.join(home(shareDir=True), "builder", "amberfiles"))


def listFiles():
    """Lists all AMBER forcefield files available in HTMD

    Example
    -------
    >>> from htmd.builder import amber
    >>> amber.listFiles()             # doctest: +ELLIPSIS
    ---- Forcefield files list: ... ----
    leaprc.amberdyes
    leaprc.conste
    leaprc.constph
    leaprc.DNA.bsc1
    ...
    """

    amberhome = defaultAmberHome()

    # Original AMBER FFs
    ffdir = join(amberhome, _defaultAmberSearchPaths["ff"])
    ffs = glob(join(ffdir, "*"))
    print("---- Forcefield files list: " + join(ffdir, "") + " ----")
    for f in sorted(ffs, key=str.lower):
        if os.path.isdir(f):
            continue
        print(f.replace(join(ffdir, ""), ""))

    oldffdir = join(amberhome, _defaultAmberSearchPaths["ff"], "oldff")
    ffs = glob(join(oldffdir, "*"))
    print("---- OLD Forcefield files list: " + join(ffdir, "") + " ----")
    for f in sorted(ffs, key=str.lower):
        print(f.replace(join(ffdir, ""), ""))

    topodir = os.path.join(amberhome, _defaultAmberSearchPaths["topo"])
    topos = glob(join(topodir, "*"))
    print("---- Topology files list: " + join(topodir, "") + " ----")
    for f in sorted(topos, key=str.lower):
        if os.path.isdir(f):
            continue
        print(f.replace(join(topodir, ""), ""))

    # FRCMOD files
    frcmoddir = os.path.join(amberhome, _defaultAmberSearchPaths["param"])
    ffs = glob(join(frcmoddir, "frcmod.*"))
    print("---- Parameter files list: " + join(frcmoddir, "") + " ----")
    for f in sorted(ffs, key=str.lower):
        print(f.replace(join(frcmoddir, ""), ""))

    htmdamberdir = htmdAmberHome()

    # Extra AMBER FFs on HTMD
    extraffs = glob(join(htmdamberdir, "*", "leaprc.*"))
    print("---- Extra forcefield files list: " + join(htmdamberdir, "") + " ----")
    for f in sorted(extraffs, key=str.lower):
        print(f.replace(join(htmdamberdir, ""), ""))

    # Extra AMBER FFs on HTMD (*.frcmod, *.in) @cuzzo87
    extratopos = glob(join(htmdamberdir, "*", "*.in"))
    print("---- Extra topology files list: " + join(htmdamberdir, "") + " ----")
    for f in sorted(extratopos, key=str.lower):
        print(f.replace(join(htmdamberdir, ""), ""))

    extraparams = glob(join(htmdamberdir, "*", "*.frcmod"))
    print("---- Extra parameter files list: " + join(htmdamberdir, "") + " ----")
    for f in sorted(extraparams, key=str.lower):
        print(f.replace(join(htmdamberdir, ""), ""))


def _locateFile(fname, ftype, teleap):
    amberhome = defaultAmberHome(teleap=teleap)
    htmdamberdir = htmdAmberHome()
    searchdir = os.path.join(amberhome, _defaultAmberSearchPaths[ftype])
    foundfile = glob(os.path.join(searchdir, fname))
    if len(foundfile) != 0:
        return foundfile[0]
    foundfile = glob(os.path.join(htmdamberdir, fname))
    if len(foundfile) != 0:
        return foundfile[0]
    logger.warning(f"Was not able to find {ftype} file {fname}")


def defaultFf():
    """Returns the default leaprc forcefield files used by amber.build"""
    return [
        "leaprc.protein.ff19SB",
        "leaprc.lipid17",
        "leaprc.gaff2",
        "leaprc.RNA.Shaw",
        "leaprc.DNA.bsc1",
        "leaprc.water.tip3p",
    ]


def defaultTopo():
    """Returns the default topology `prepi` files used by amber.build"""
    return []


def defaultParam():
    """Returns the default parameter `frcmod` files used by amber.build"""
    return []


def _prepareMolecule(mol, caps, disulfide):
    # Remove pdb protein bonds as they can be regenerated by tleap. Keep non-protein bonds i.e. for ligands
    _removeProteinBonds(mol)

    # Check for missing segids or mixed protein / non-protein segments
    _missingSegID(mol)
    _checkMixedSegment(mol)

    # Convert lipids to AMBER naming
    mol = _charmmLipid2Amber(mol)

    # Add caps to termini
    if caps is None:
        caps = _defaultProteinCaps(mol)
    _add_caps(mol, caps)

    # Before modifying the resids copy the molecule to map back the disulfide bonds
    mol_orig_resid = mol.copy()

    # We need to renumber residues to unique numbers for teLeap. It goes up to 9999 and restarts from 0
    mol.resid[:] = (sequenceID((mol.resid, mol.insertion, mol.segid)) + 1) % 10000

    # curr_resid = 0
    # prev_combo = (None, None, None)
    # for i in range(mol.numAtoms):
    #     curr_combo = (mol.resid[i], mol.insertion[i], mol.segid[i])
    #     if prev_combo != curr_combo:
    #         curr_resid += 1
    #         if prev_combo[0] is not None and curr_combo[0] - prev_combo[0] > 1:
    #             curr_resid += 1  # Insert a resid gap if a gap existed before
    #         prev_combo = curr_combo

    #     mol.resid[i] = curr_resid % 10000

    # Map the old disulfide UniqueResidueIDs to the new ones
    if disulfide is not None and len(disulfide):
        if not isinstance(disulfide[0][0], str):
            raise RuntimeError("Can only accept disulfide bond strings")
        disulfide = convertDisulfide(mol_orig_resid, disulfide)
        disulfide = _mapDisulfide(disulfide, mol, mol_orig_resid)
    else:
        logger.info("Detecting disulfide bonds.")
        disulfide = detectDisulfideBonds(mol)

    # Fix structure to match the disulfide patching
    if len(disulfide) != 0:
        torem = np.zeros(mol.numAtoms, dtype=bool)
        for d1, d2 in disulfide:
            # Rename the residues to CYX if there is a disulfide bond
            atoms1 = d1.selectAtoms(mol, indexes=False)
            atoms2 = d2.selectAtoms(mol, indexes=False)
            d1.resname = "CYX"
            d2.resname = "CYX"
            mol.resname[atoms1] = "CYX"
            mol.resname[atoms2] = "CYX"
            # Remove (eventual) HG hydrogens on these CYS (from systemPrepare)
            torem |= (atoms1 & (mol.name == "HG")) | (atoms2 & (mol.name == "HG"))
        mol.remove(torem, _logger=False)

    return disulfide


def build(
    mol,
    ff=None,
    topo=None,
    param=None,
    prefix="structure",
    outdir="./build",
    caps=None,
    ionize=True,
    saltconc=0,
    saltanion=None,
    saltcation=None,
    disulfide=None,
    teleap=None,
    teleapimports=None,
    execute=True,
    atomtypes=None,
    offlibraries=None,
    gbsa=False,
    igb=2,
):
    """Builds a system for AMBER

    Uses tleap to build a system for AMBER. Additionally it allows the user to ionize and add disulfide bridges.

    Parameters
    ----------
    mol : :class:`Molecule <moleculekit.molecule.Molecule>` object
        The Molecule object containing the system
    ff : list of str
        A list of leaprc forcefield files.
        Use :func:`amber.listFiles <htmd.builder.amber.listFiles>` to get a list of available forcefield files.
        Default: :func:`amber.defaultFf <htmd.builder.amber.defaultFf>`
    topo : list of str
        A list of topology `prepi/prep/in` files.
        Use :func:`amber.listFiles <htmd.builder.amber.listFiles>` to get a list of available topology files.
        Default: :func:`amber.defaultTopo <htmd.builder.amber.defaultTopo>`
    param : list of str
        A list of parameter `frcmod` files.
        Use :func:`amber.listFiles <htmd.builder.amber.listFiles>` to get a list of available parameter files.
        Default: :func:`amber.defaultParam <htmd.builder.amber.defaultParam>`
    prefix : str
        The prefix for the generated pdb and psf files
    outdir : str
        The path to the output directory
        Default: './build'
    caps : dict
        A dictionary with keys segids and values lists of strings describing the caps for a particular protein segment.
        e.g. caps['P'] = ['ACE', 'NME'] or caps['P'] = ['none', 'none']. Default: will apply ACE and NME caps to every
        protein segment.
    ionize : bool
        Enable or disable ionization
    saltconc : float
        Salt concentration to add to the system after neutralization.
    saltanion : {'Cl-'}
        The anion type. Please use only AMBER ion atom names.
    saltcation : {'Na+', 'K+', 'Cs+'}
        The cation type. Please use only AMBER ion atom names.
    disulfide : list of pairs of atomselection strings
        If None it will guess disulfide bonds. Otherwise provide a list pairs of atomselection strings for each pair of
        residues forming the disulfide bridge.
    teleap : str
        Path to teLeap executable used to build the system for AMBER
    teleapimports : list
        A list of paths to pass to teLeap '-I' flag, i.e. directories to be searched
        Default: determined from :func:`amber.defaultAmberHome <htmd.builder.amber.defaultAmberHome>` and
        :func:`amber.htmdAmberHome <htmd.builder.amber.htmdAmberHome>`
    execute : bool
        Disable building. Will only write out the input script needed by tleap. Does not include ionization.
    atomtypes : list of triplets
        Custom atom types defined by the user as ('type', 'element', 'hybrid') triplets
        e.g. (('C1', 'C', 'sp2'), ('CI', 'C', 'sp3')). Check `addAtomTypes` in AmberTools docs.
    offlibraries : str or list
        A path or a list of paths to OFF library files. Check `loadOFF` in AmberTools docs.
    gbsa : bool
        Modify radii for GBSA implicit water model
    igb : int
        GB model. Select: 1 for mbondi, 2 and 5 for mbondi2, 7 for bondi and 8 for mbondi3.
        Check section 4. The Generalized Born/Surface Area Model of the AMBER manual.

    Returns
    -------
    molbuilt : :class:`Molecule <moleculekit.molecule.Molecule>` object
        The built system in a Molecule object

    Example
    -------
    >>> from htmd.ui import *  # doctest: +SKIP
    >>> mol = Molecule("3PTB")
    >>> molbuilt = amber.build(mol, outdir='/tmp/build')  # doctest: +SKIP
    >>> # More complex example
    >>> disu = [['segid P and resid 157', 'segid P and resid 13'], ['segid K and resid 1', 'segid K and resid 25']]
    >>> molbuilt = amber.build(mol, outdir='/tmp/build', saltconc=0.15, disulfide=disu)  # doctest: +SKIP
    """
    mol = mol.copy()

    disulfide = _prepareMolecule(mol, caps, disulfide)

    if ionize:
        molbuilt = _build(
            mol,
            ff=ff,
            topo=topo,
            param=param,
            prefix=prefix,
            outdir=outdir,
            disulfide=disulfide,
            teleap=teleap,
            teleapimports=teleapimports,
            execute=execute,
            atomtypes=atomtypes,
            offlibraries=offlibraries,
            gbsa=gbsa,
            igb=igb,
        )
        shutil.move(
            os.path.join(outdir, "structure.crd"),
            os.path.join(outdir, "structure.noions.crd"),
        )
        shutil.move(
            os.path.join(outdir, "structure.prmtop"),
            os.path.join(outdir, "structure.noions.prmtop"),
        )
        totalcharge = np.sum(molbuilt.charge)
        nwater = np.sum(molbuilt.atomselect("water and noh"))
        anion, cation, anionatom, cationatom, nanion, ncation = ionizef(
            totalcharge,
            nwater,
            saltconc=saltconc,
            anion=saltanion,
            cation=saltcation,
        )
        mol = ionizePlace(mol, anion, cation, anionatom, cationatom, nanion, ncation)

    molbuilt = _build(
        mol,
        ff=ff,
        topo=topo,
        param=param,
        prefix=prefix,
        outdir=outdir,
        disulfide=disulfide,
        teleap=teleap,
        teleapimports=teleapimports,
        execute=execute,
        atomtypes=atomtypes,
        offlibraries=offlibraries,
        gbsa=gbsa,
        igb=igb,
    )
    return molbuilt


def _build(
    mol,
    ff=None,
    topo=None,
    param=None,
    prefix="structure",
    outdir="./build",
    disulfide=None,
    teleap=None,
    teleapimports=None,
    execute=True,
    atomtypes=None,
    offlibraries=None,
    gbsa=False,
    igb=2,
):
    if teleap is None:
        teleap = _findTeLeap()
    else:
        if shutil.which(teleap) is None:
            raise NameError(
                f"Could not find executable: `{teleap}` in the PATH. Cannot build for AMBER. Please install it with `conda install ambertools -c conda-forge`"
            )

    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    _cleanOutDir(outdir)
    if ff is None:
        ff = defaultFf()
    if topo is None:
        topo = defaultTopo()
    if param is None:
        param = defaultParam()

    with open(os.path.join(outdir, "tleap.in"), "w") as f:
        f.write("# tleap file generated by amber.build\n")

        # Printing out the forcefields
        for i, force in enumerate(ensurelist(ff)):
            if not os.path.isfile(force):
                force = _locateFile(force, "ff", teleap)
                if force is None:
                    continue
            newname = f"ff{i}_{os.path.basename(force)}"
            shutil.copy(force, os.path.join(outdir, newname))
            f.write(f"source {newname}\n")
        f.write("\n")

        if gbsa:
            gbmodels = {
                1: "mbondi",
                2: "mbondi2",
                5: "mbondi2",
                7: "bondi",
                8: "mbondi3",
            }
            f.write(f"set default PBradii {gbmodels[igb]}\n\n")

        # Adding custom atom types
        if atomtypes is not None:
            atomtypes = ensurelist(tocheck=atomtypes[0], tomod=atomtypes)
            f.write("addAtomTypes {\n")
            for at in atomtypes:
                if len(at) != 3:
                    raise RuntimeError(
                        "Atom type definitions have to be triplets. Check the AMBER documentation."
                    )
                f.write(f'    {{ "{at[0]}" "{at[1]}" "{at[2]}" }}\n')
            f.write("}\n\n")

        # Loading OFF libraries
        if offlibraries is not None:
            offlibraries = ensurelist(offlibraries)
            for i, off in enumerate(offlibraries):
                if not os.path.isfile(off):
                    raise RuntimeError(f"Could not find off-library in location {off}")
                newname = f"offlib{i}_{os.path.basename(off)}"
                shutil.copy(off, os.path.join(outdir, newname))
                f.write(f"loadoff {newname}\n")

        # Copy param and topo files to output folder and rename to unique names
        newparam = []
        for i, fname in enumerate(sorted(param)):
            if not os.path.isfile(fname):
                fname = _locateFile(fname, "param", teleap)
                if fname is None:
                    continue
            newname = os.path.join(outdir, f"param{i}_{os.path.basename(fname)}")
            shutil.copy(fname, newname)
            newparam.append(newname)

        newtopo = []
        for i, fname in enumerate(sorted(topo)):
            if not os.path.isfile(fname):
                fname = _locateFile(fname, "topo", teleap)
                if fname is None:
                    continue
            newname = os.path.join(outdir, f"topo{i}_{os.path.basename(fname)}")
            shutil.copy(fname, newname)
            newtopo.append(newname)

        _fix_prepi_atomname_capitalization(mol, newtopo)
        _fix_parameterize_atomtype_collisions(mol, newparam, newtopo)

        # Loading frcmod parameters
        f.write("# Loading parameter files\n")
        for fname in newparam:
            f.write(f"loadamberparams {os.path.basename(fname)}\n")
        f.write("\n")

        # Loading prepi topologies
        f.write("# Loading prepi topologies\n")
        for fname in newtopo:
            f.write(f"loadamberprep {os.path.basename(fname)}\n")
        f.write("\n")

        if np.any(mol.atomtype == ""):
            f.write("# Loading the system\n")
            f.write("mol = loadpdb input.pdb\n\n")

        if np.sum(mol.atomtype != "") != 0:
            f.write("# Loading the ligands\n")
            segs = np.unique(mol.segid[mol.atomtype != ""])

            # teLeap crashes if you try to combine too many molecules in a single command so we will do them by 10s
            for k in range(0, len(segs), 10):
                segments_string = ""
                for seg in segs[k : min(k + 10, len(segs))]:
                    name = f"segment{seg}"
                    segments_string += f" {name}"

                    mol2name = os.path.join(outdir, f"{name}.mol2")
                    mol.write(mol2name, (mol.atomtype != "") & (mol.segid == seg))
                    if not os.path.isfile(mol2name):
                        raise NameError("Failed writing ligand mol2 file.")

                    f.write(f"{name} = loadmol2 {name}.mol2\n")
                f.write(f"mol = combine {{mol{segments_string}}}\n\n")

        # Write disulfide patches
        if len(disulfide) != 0:
            f.write("# Adding disulfide bonds\n")
            for d in disulfide:
                atoms1 = d[0].selectAtoms(mol, indexes=False)
                atoms2 = d[1].selectAtoms(mol, indexes=False)
                uqres1 = int(np.unique(mol.resid[atoms1]))
                uqres2 = int(np.unique(mol.resid[atoms2]))
                f.write(f"bond mol.{uqres1}.SG mol.{uqres2}.SG\n")
            f.write("\n")

        # Calculate the bounding box and store it in the CRD file
        f.write('setBox mol "vdw"\n\n')

        f.write("# Writing out the results\n")
        f.write(f"saveamberparm mol {prefix}.prmtop {prefix}.crd\n")
        f.write("quit")

    # mol2 files have atomtype, here we only write parts not coming from mol2
    # We need to write the input.pdb at the end since we modify the resname for disulfide bridges in mol
    if np.any(mol.atomtype == ""):
        # Printing and loading the PDB file. AMBER can work with a single PDB file if the segments are separate by TER
        logger.debug("Writing PDB file for input to tleap.")
        pdbname = os.path.join(outdir, "input.pdb")

        mol.write(pdbname, mol.atomtype == "")
        if not os.path.isfile(pdbname):
            raise NameError("Could not write a PDB file out of the given Molecule.")

    if execute:
        if not teleapimports:
            teleapimports = []
            # Source default Amber (i.e. the same paths tleap imports)
            amberhome = defaultAmberHome(teleap=teleap)
            teleapimports += [
                os.path.join(amberhome, s) for s in _defaultAmberSearchPaths.values()
            ]
            if len(teleapimports) == 0:
                raise RuntimeWarning(
                    f"No default Amber force-field found. Check teLeap location: {teleap}"
                )
            # Source HTMD Amber paths that contain ffs
            htmdamberdir = htmdAmberHome()
            teleapimports += [
                os.path.join(htmdamberdir, os.path.dirname(f))
                for f in ff
                if os.path.isfile(os.path.join(htmdamberdir, f))
            ]
            if len(teleapimports) == 0:
                raise RuntimeError(
                    "No default Amber force-field imports found. Check "
                    "`htmd.builder.amber.defaultAmberHome()` and `htmd.builder.amber.htmdAmberHome()`"
                )

        # Set import flags for teLeap
        teleapimportflags = []
        for p in teleapimports:
            teleapimportflags.append("-I")
            teleapimportflags.append(str(p))
        logpath = os.path.abspath(os.path.join(outdir, "log.txt"))
        logger.info("Starting the build.")
        currdir = os.getcwd()
        os.chdir(outdir)
        f = open(logpath, "w")
        try:
            cmd = [teleap, "-f", "./tleap.in"]
            cmd[1:1] = teleapimportflags
            logger.debug(cmd)
            call(cmd, stdout=f)
        except Exception:
            raise NameError("teLeap failed at execution")
        f.close()
        errors = _logParser(logpath)
        os.chdir(currdir)
        if errors:
            raise BuildError(
                errors
                + [f"Check {logpath} for further information on errors in building."]
            )
        logger.info("Finished building.")

        if (
            os.path.exists(os.path.join(outdir, "structure.crd"))
            and os.path.getsize(os.path.join(outdir, "structure.crd")) != 0
            and os.path.getsize(os.path.join(outdir, "structure.prmtop")) != 0
        ):
            try:
                molbuilt = Molecule(os.path.join(outdir, "structure.prmtop"))
                molbuilt.read(os.path.join(outdir, "structure.crd"))
            except Exception as e:
                raise RuntimeError(
                    f"Failed at reading structure.prmtop/structure.crd due to error: {e}"
                )
        else:
            raise BuildError(
                f"No structure pdb/prmtop file was generated. Check {logpath} for errors in building."
            )

        tmpbonds = molbuilt.bonds
        molbuilt.bonds = []  # Removing the bonds to speed up writing
        molbuilt.write(os.path.join(outdir, "structure.pdb"))
        molbuilt.bonds = tmpbonds  # Restoring the bonds
        detectCisPeptideBonds(molbuilt, respect_bonds=True)  # Warn in case of cis bonds
        return molbuilt


def _add_caps(mol: Molecule, caps: dict):
    capdir = os.path.join(home(shareDir=True), "builder", "caps")

    remove_atoms = {
        "ACE": ["H1", "H2", "H3", "HT1", "HT2", "HT3", "H"],
        "NME": ["OXT", "OT1", "O"],
    }

    # For each caps definition
    for seg in caps:
        # Can't move this out since we remove atoms in this loop
        prot = mol.atomselect("protein")
        # Get the segment
        segment = np.where(mol.segid == seg)[0]
        # Test segment
        if len(segment) == 0:
            raise RuntimeError(f"There is no segment {seg} in the molecule.")
        if not np.any(prot & (mol.segid == seg)):
            raise RuntimeError(
                f"Segment {seg} is not protein. Capping for non-protein segments is not supported."
            )
        # For each cap
        for i, cap in enumerate(caps[seg]):
            if cap is None or (isinstance(cap, str) and cap == "none"):
                continue

            # Get info on segment and its terminals
            segidm = mol.segid == seg
            segididx = np.where(segidm)[0]
            terminalresids = [mol.resid[segididx][0], mol.resid[segididx][-1]]
            residm = mol.resid == terminalresids[i]  # Mask for resid
            mask = residm & segidm
            resname = mol.resname[mask][0]

            capmol = Molecule(os.path.join(capdir, f"{cap}.pdb"))
            align_names = capmol.name[capmol.beta == 1]
            mol_idx = np.where(np.isin(mol.name, align_names) & mask)[0]
            # Ensuring the atom order matches for the alignment
            cap_idx = [
                np.where((capmol.name == nn) & (capmol.resname == "XXX"))[0][0]
                for nn in mol.name[mol_idx]
            ]

            if len(cap_idx) != len(mol_idx):
                raise RuntimeError("Could not find all required backbone atoms!")

            capmol.align(cap_idx, refmol=mol, refsel=mol_idx)
            capmol.resname[capmol.resname == "XXX"] = resname
            capmol.segid[:] = seg
            capmol.resid[:] += terminalresids[i]
            capmol.chain[:] = mol.chain[mask][0]
            capmol.remove(cap_idx, _logger=False)  # Remove atoms which were aligned

            # Remove the atoms defined in remove_atoms to clean up the termini
            removed = mol.remove(
                np.isin(mol.name, remove_atoms[cap]) & mask, _logger=False
            )
            segidm = np.delete(segidm, removed)
            segididx = np.where(segidm)[0]
            mol.insert(capmol, segididx[0] if i == 0 else segididx[-1] + 1)

    # Remove terminal hydrogens regardless of caps or no caps. tleap confuses itself when it makes residues into terminals.
    # For example HID has an atom H which in NHID should become H[123] and crashes tleap.
    for seg in np.unique(mol.get("segid", "protein")):
        segidm = mol.segid == seg  # Mask for segid
        segididx = np.where(segidm)[0]
        resids = mol.resid[segididx]
        mol.remove(
            f'(resid "{resids[0]}" "{resids[-1]}") and segid {seg} and hydrogen',
            _logger=False,
        )


def _removeProteinBonds(mol):
    # Keeping just bonds with atomtypes to catch ligand cases. Bad heuristic
    segs = np.unique(mol.segid[mol.atomtype != ""])
    mol.deleteBonds(~np.in1d(mol.segid, segs))


def _defaultProteinCaps(mol):
    # Defines ACE and NME (neutral terminals) as default for protein segments
    # Of course, this might not be ideal for proteins that require charged terminals
    segsProt = np.unique(mol.get("segid", sel="protein"))
    caps = dict()
    for s in segsProt:
        if len(np.unique(mol.resid[mol.segid == s])) < 10:
            logger.warning(
                f"Segment {s} consists of a peptide with less than 10 residues. It will not be capped by "
                "default. If you want to cap it use the caps argument of amber.build to manually define caps"
                "for all segments."
            )
            continue
        caps[s] = ["ACE", "NME"]
    return caps


def _cleanOutDir(outdir):
    from glob import glob

    files = glob(os.path.join(outdir, "structure.*"))
    files += glob(os.path.join(outdir, "log.*"))
    files += glob(os.path.join(outdir, "*.log"))
    for f in files:
        os.remove(f)


def _charmmLipid2Amber(mol):
    """Convert a CHARMM lipid membrane to AMBER format

    Parameters
    ----------
    mol : :class:`Molecule <moleculekit.molecule.Molecule>` object
        The Molecule object containing the membrane

    Returns
    -------
    newmol : :class:`Molecule <moleculekit.molecule.Molecule>` object
        A new Molecule object with the membrane converted to AMBER
    """

    resdict = _readcsvdict(
        os.path.join(home(shareDir=True), "builder", "charmmlipid2amber.csv")
    )

    natoms = mol.numAtoms
    neworder = np.array(
        list(range(natoms))
    )  # After renaming the atoms and residues I have to reorder them

    begs = np.zeros(natoms, dtype=bool)
    fins = np.zeros(natoms, dtype=bool)
    begters = np.zeros(natoms, dtype=bool)
    finters = np.zeros(natoms, dtype=bool)

    # Iterate over the translation dictionary
    incrresids = sequenceID((mol.resid, mol.insertion, mol.segid))

    for res in resdict.keys():
        molresidx = mol.resname == res
        if not np.any(molresidx):
            continue
        names = (
            mol.name.copy()
        )  # Need to make a copy or I accidentally double-modify atoms

        atommap = resdict[res]
        for atom in atommap.keys():
            rule = atommap[atom]

            molatomidx = np.zeros(len(names), dtype=bool)
            molatomidx[molresidx] = names[molresidx] == atom

            mol.set("resname", rule.replaceresname, sel=molatomidx)
            mol.set("name", rule.replaceatom, sel=molatomidx)
            neworder[molatomidx] = rule.order

            if rule.order == 0:  # First atom (with or without ters)
                begs[molatomidx] = True
            if rule.order == rule.natoms - 1:  # Last atom (with or without ters)
                fins[molatomidx] = True
            if rule.order == 0 and rule.ter:  # First atom with ter
                begters[molatomidx] = True
            if rule.order == rule.natoms - 1 and rule.ter:  # Last atom with ter
                finters[molatomidx] = True

    uqresids = np.unique(incrresids[begs])
    residuebegs = np.ones(len(uqresids), dtype=int) * -1
    residuefins = np.ones(len(uqresids), dtype=int) * -1
    for i in range(len(uqresids)):
        residuebegs[i] = np.where(incrresids == uqresids[i])[0][0]
        residuefins[i] = np.where(incrresids == uqresids[i])[0][-1]
    for i in range(len(residuebegs)):
        beg = residuebegs[i]
        fin = residuefins[i] + 1
        neworder[beg:fin] = neworder[beg:fin] + beg
    idx = np.argsort(neworder)

    _reorderMol(mol, idx)

    begters = np.where(begters[idx])[0]  # Sort the begs and ters
    finters = np.where(finters[idx])[0]

    # if len(begters) > 999:
    #    raise NameError('More than 999 lipids. Cannot define separate segments for all of them.')

    for i in range(len(begters)):
        mapping = np.zeros(len(mol.resid), dtype=bool)
        mapping[begters[i] : finters[i] + 1] = True
        mol.set("resid", sequenceID(mol.get("resname", sel=mapping)), sel=mapping)
        mol.set("segid", f"L{i % 2}", sel=mapping)

    return mol


def _reorderMol(mol, order):
    for k in mol._atom_and_coord_fields:
        if mol.__dict__[k] is not None and np.size(mol.__dict__[k]) != 0:
            if k == "coords":
                mol.__dict__[k] = mol.__dict__[k][order, :, :]
            else:
                mol.__dict__[k] = mol.__dict__[k][order]


def _readcsvdict(filename):
    import csv
    from collections import namedtuple

    if os.path.isfile(filename):
        csvfile = open(filename, "r")
    else:
        raise NameError("File " + filename + " does not exist")

    resdict = dict()

    Rule = namedtuple(
        "Rule", ["replaceresname", "replaceatom", "order", "natoms", "ter"]
    )

    # Skip header line of csv file. Line 2 contains dictionary keys:
    csvfile.readline()
    csvreader = csv.DictReader(csvfile)
    for line in csvreader:
        searchres = line["search"].split()[1]
        searchatm = line["search"].split()[0]
        if searchres not in resdict:
            resdict[searchres] = dict()
        resdict[searchres][searchatm] = Rule(
            line["replace"].split()[1],
            line["replace"].split()[0],
            int(line["order"]),
            int(line["num_atom"]),
            line["TER"] == "True",
        )
    csvfile.close()

    return resdict


def _mapDisulfide(disulfide, mol, mol_orig):
    from moleculekit.molecule import UniqueResidueID

    disulfide_new = []
    for dd1, dd2 in disulfide:
        idx1 = dd1.selectAtoms(mol_orig)
        idx2 = dd2.selectAtoms(mol_orig)
        uqnew1 = UniqueResidueID.fromMolecule(mol, idx=idx1)
        uqnew2 = UniqueResidueID.fromMolecule(mol, idx=idx2)
        disulfide_new.append([uqnew1, uqnew2])
    return disulfide_new


def _logParser(fname):
    import re

    unknownres_regex = re.compile(r"Unknown residue:\s+(\w+)")
    missingparam_regex = re.compile(
        r"For atom: (.*) Could not find vdW \(or other\) parameters for type:\s+(\w+)"
    )
    missingtorsion_regex = re.compile(r"No torsion terms for\s+(.*)$")
    missingbond_regex = re.compile(r"Could not find bond parameter for:\s+(.*)$")
    missingangle_regex = re.compile(r"Could not find angle parameter:\s+(.*)$")
    missingatomtype_regex = re.compile(r"FATAL:\s+Atom (.*) does not have a type")

    unknownres = []
    missingparam = []
    missingtorsion = []
    missingbond = []
    missingangle = []
    missingatomtype = []
    with open(fname, "r") as f:
        for line in f:
            if unknownres_regex.search(line):
                unknownres.append(unknownres_regex.findall(line)[0])
            if missingparam_regex.search(line):
                missingparam.append(missingparam_regex.findall(line)[0])
            if missingtorsion_regex.search(line):
                missingtorsion.append(missingtorsion_regex.findall(line)[0])
            if missingbond_regex.search(line):
                missingbond.append(missingbond_regex.findall(line)[0])
            if missingangle_regex.search(line):
                missingangle.append(missingangle_regex.findall(line)[0])
            if missingatomtype_regex.search(line):
                missingatomtype.append(missingatomtype_regex.findall(line)[0])

    errors = []
    if len(unknownres):
        errors.append(
            UnknownResidueError(
                f"Unknown residue(s) {np.unique(unknownres)} found in the input structure. "
                "You are either missing a topology definition for the residue or you need to "
                "rename it to the correct residue name"
            )
        )
    if len(missingparam):
        errors.append(
            MissingParameterError(
                f"Missing parameters for atom {missingparam} and type {missingparam}"
            )
        )
    if len(missingtorsion):
        errors.append(
            MissingTorsionError(f"Missing torsion terms for {missingtorsion}")
        )
    if len(missingbond):
        errors.append(MissingBondError(f"Missing bond parameters for {missingbond}"))
    if len(missingangle):
        errors.append(MissingAngleError(f"Missing angle parameters for {missingangle}"))
    if len(missingatomtype):
        errors.append(MissingAtomTypeError(f"Missing atom type for {missingatomtype}"))

    return errors


def _resname_from_fname(ff):
    return os.path.splitext(os.path.basename(ff))[0].split("_", maxsplit=1)[1]


def _fix_prepi_atomname_capitalization(mol, prepis):
    for fname in prepis:
        bn = _resname_from_fname(fname)
        if bn not in mol.resname:
            raise RuntimeError(
                f"Could not find residue {bn} in mol to correspond to prepi file {fname}"
            )

        uqnames = {x.upper(): x for x in np.unique(mol.name[mol.resname == bn])}
        with open(fname, "r") as f:
            lines = f.readlines()

        with open(fname, "w") as f:
            atomregion = None
            for i in range(len(lines)):
                line = lines[i]
                if atomregion is None and i == 8:
                    atomregion = True
                if atomregion is None or not atomregion:
                    f.write(line)
                else:
                    if line.strip() == "":
                        atomregion = False
                        f.write(line)
                        continue
                    if line[6:10] == "DUMM":
                        f.write(line)
                        continue
                    original = line[6:9].strip()
                    fixedname = uqnames[original.upper()]
                    if original != fixedname:
                        logger.info(
                            f"Fixed residue {bn} atom name {original} -> {fixedname} to match the input structure."
                        )
                        ll = f"{line[:6]}{fixedname:4s}{line[10:]}"
                        f.write(ll)
                    else:
                        f.write(line)


def _fix_parameterize_atomtype_collisions(mol, params, prepis):
    import itertools
    import string

    prefixes = ["z", "x", "y", "w"]
    gen = itertools.product(*[prefixes, string.ascii_lowercase])

    def _fix_frcmod(fname, repl):
        with open(fname, "r") as f:
            lines = f.readlines()

        const = ("", "MASS", "BOND", "ANGLE", "DIHE", "IMPROPER", "NONB")
        with open(fname, "w") as f:
            f.write("Created by HTMD\n")
            for line in lines[1:]:
                if line.strip() in const:
                    f.write(line)
                    continue
                # Split on two white spaces. Some atom types have a white space H - N -zs for example
                types, rest = line.split(sep="  ", maxsplit=1)
                types = types.split("-")
                for i in range(len(types)):
                    if types[i] in repl:
                        types[i] = repl[types[i]]
                f.write("-".join(types) + "  " + rest)

    def _fix_prepi(fname, repl):
        with open(fname, "r") as f:
            lines = f.readlines()

        for i in range(7, len(lines)):
            if lines[i].strip() == "":
                break
            old_at = lines[i][12:14]
            if old_at in repl:
                lines[i] = lines[i][:12] + repl[old_at] + lines[i][14:]

        with open(fname, "w") as f:
            for line in lines:
                f.write(line)

    def _fix_mol(bn, mol, repl):
        idx = np.where(mol.resname == bn)[0]
        for i in idx:
            if mol.atomtype[i] in repl:
                mol.atomtype[i] = repl[mol.atomtype[i]]

    # Match prepis to frcmods
    prepi_bn = {_resname_from_fname(x): x for x in prepis}
    frcmd_bn = {_resname_from_fname(x): x for x in params}
    replacements = {}
    atomtypes = []
    for bn in frcmd_bn:
        replacements[bn] = {}

        # Find all parameterize atom types in the frcmod file
        with open(frcmd_bn[bn], "r") as f:
            file_at = []
            for line in f.readlines()[2:]:
                if line.strip() == "":
                    break
                at = line.split()[0]
                if at[0] not in prefixes:
                    continue
                file_at.append(at)

        # Check for collisions with previous frcmod files and invent new type
        for at in file_at:
            if at in atomtypes:
                # Invent new atom type and rename in frcmod
                new_at = "".join(next(gen))
                while new_at in atomtypes:
                    new_at = "".join(next(gen))

                atomtypes.append(new_at)
                replacements[bn][at] = new_at
                logger.info(
                    f"Converting {bn} atom type {at} to {new_at} to avoid collisions."
                )
            else:
                atomtypes.append(at)

    # Correct all atom types to the new ones
    for bn in replacements:
        _fix_frcmod(frcmd_bn[bn], replacements[bn])
        if bn in prepi_bn:
            _fix_prepi(prepi_bn[bn], replacements[bn])

        if bn in mol.resname:
            _fix_mol(bn, mol, replacements[bn])
        else:
            raise RuntimeError(
                f"Could not find residue {bn} in the input structure. Please ensure that the frcmod / prepi files are named as RES.frcmod / RES.prepi where RES the residue name to which they correspond."
            )


class _TestAmberBuild(unittest.TestCase):
    currentResult = None  # holds last result object passed to run method

    def setUp(self):
        from htmd.util import tempname

        self.testDir = os.environ.get("TESTDIR", tempname())
        print(f"Running tests in {self.testDir}")

    def run(self, result=None):
        self.currentResult = result  # remember result for use in tearDown
        unittest.TestCase.run(self, result)  # call superclass run method

    def tearDown(self):
        pass
        # if self.currentResult.wasSuccessful():
        #     shutil.rmtree(self.testDir)

    @staticmethod
    def _compareResultFolders(
        compare, tmpdir, pid, ignore_ftypes=(".log", ".txt", ".frcmod")
    ):
        import filecmp

        def _cutfirstline(infile, outfile):
            # Cut out the first line of prmtop which has a build date in it
            with open(infile, "r") as fin:
                data = fin.read().splitlines(True)
            with open(outfile, "w") as fout:
                fout.writelines(data[1:])

        files = []
        deletefiles = []
        for f in glob(join(compare, "*")):
            fname = os.path.basename(f)
            if os.path.splitext(f)[1] in ignore_ftypes:
                continue
            if f.endswith("prmtop"):
                _cutfirstline(f, join(compare, fname + ".mod"))
                _cutfirstline(join(tmpdir, fname), os.path.join(tmpdir, fname + ".mod"))
                files.append(os.path.basename(f) + ".mod")
                deletefiles.append(join(compare, fname + ".mod"))
            else:
                files.append(os.path.basename(f))

        match, mismatch, error = filecmp.cmpfiles(tmpdir, compare, files, shallow=False)
        if len(mismatch) != 0 or len(error) != 0 or len(match) != len(files):
            raise RuntimeError(
                f"Different results produced by amber.build for test {pid} between {compare} and {tmpdir} in files {mismatch}."
            )

        for f in deletefiles:
            os.remove(f)

    def test_with_protein_prepare(self):
        from moleculekit.tools.preparation import systemPrepare
        from htmd.builder.solvate import solvate
        from moleculekit.tools.autosegment import autoSegment

        # Test with systemPrepare
        pdbids = ["3PTB"]
        # pdbids = ['3PTB', '1A25', '1GZM']  # '1U5U' out because it has AR0 (no parameters)
        for pid in pdbids:
            np.random.seed(1)
            mol = Molecule(pid)
            mol.filter("protein")
            mol = systemPrepare(mol, pH=7.0)
            mol.filter("protein")  # Fix for bad systemPrepare hydrogen placing
            mol = autoSegment(mol)
            smol = solvate(mol)
            ffs = defaultFf()
            tmpdir = os.path.join(self.testDir, "withProtPrep", pid)
            _ = build(smol, ff=ffs, outdir=tmpdir)

            refdir = home(dataDir=join("test-amber-build", "pp", pid))
            _TestAmberBuild._compareResultFolders(refdir, tmpdir, pid)

    def test_without_protein_prepare(self):
        from htmd.builder.solvate import solvate

        # Test without systemPrepare
        pdbids = ["3PTB"]
        # pdbids = ['3PTB', '1A25', '1GZM', '1U5U']
        for pid in pdbids:
            np.random.seed(1)
            mol = Molecule(pid)
            mol.filter("protein")
            smol = solvate(mol)
            ffs = defaultFf()
            tmpdir = os.path.join(self.testDir, "withoutProtPrep", pid)
            _ = build(smol, ff=ffs, outdir=tmpdir)

            refdir = home(dataDir=join("test-amber-build", "nopp", pid))
            _TestAmberBuild._compareResultFolders(refdir, tmpdir, pid)

    def test_protein_ligand(self):
        from htmd.builder.solvate import solvate

        # Test protein ligand building with parametrized ligand
        refdir = home(dataDir=join("test-amber-build", "protLig"))
        tmpdir = os.path.join(self.testDir, "protLig")
        os.makedirs(tmpdir)

        mol = Molecule(join(refdir, "3ptb_mod.pdb"))
        lig = Molecule(join(refdir, "benzamidine.mol2"))
        lig.segid[:] = "L"

        # params =
        newmol = Molecule()
        newmol.append(mol)
        newmol.append(lig)
        smol = solvate(newmol)

        params = defaultParam() + [
            join(refdir, "benzamidine.frcmod"),
        ]

        _ = build(smol, outdir=tmpdir, param=params, ionize=False)

        refdir = home(dataDir=join("test-amber-build", "protLig", "results"))
        _TestAmberBuild._compareResultFolders(refdir, tmpdir, "3PTB")

    def test_custom_disulfide_bonds(self):
        from htmd.builder.solvate import solvate

        pdbids = [
            "1GZM",
        ]
        for pid in pdbids:
            np.random.seed(1)
            mol = Molecule(pid)
            mol.filter("protein")
            smol = solvate(mol)
            ffs = defaultFf()
            disu = [
                ["segid 0 and resid 110", "segid 0 and resid 187"],
                ["segid 1 and resid 110", "segid 1 and resid 187"],
            ]
            tmpdir = os.path.join(self.testDir, "withoutProtPrep", pid)
            _ = build(smol, ff=ffs, outdir=tmpdir, disulfide=disu)

            refdir = home(dataDir=join("test-amber-build", "nopp", pid))
            _TestAmberBuild._compareResultFolders(refdir, tmpdir, pid)

            np.random.seed(1)
            tmpdir = os.path.join(self.testDir, "withoutProtPrep", pid)
            _ = build(smol, ff=ffs, outdir=tmpdir)

            refdir = home(dataDir=join("test-amber-build", "nopp", pid))
            _TestAmberBuild._compareResultFolders(refdir, tmpdir, pid)

    def test_custom_teleap_imports(self):
        from htmd.builder.solvate import solvate

        pdbids = ["3PTB"]
        # pdbids = ['3PTB', '1A25', '1GZM', '1U5U']
        for pid in pdbids:
            np.random.seed(1)
            mol = Molecule(pid)
            mol.filter("protein")
            smol = solvate(mol)
            ffs = defaultFf()
            tmpdir = os.path.join(self.testDir, "withoutProtPrep", pid)

            amberhome = defaultAmberHome()
            teleapimports = [
                os.path.join(amberhome, _defaultAmberSearchPaths["ff"]),
                os.path.join(amberhome, _defaultAmberSearchPaths["lib"]),
                os.path.join(amberhome, _defaultAmberSearchPaths["param"]),
            ]

            _ = build(smol, ff=ffs, outdir=tmpdir, teleapimports=teleapimports)

            refdir = home(dataDir=join("test-amber-build", "nopp", pid))
            _TestAmberBuild._compareResultFolders(refdir, tmpdir, pid)

    def test_rna(self):
        from htmd.builder.solvate import solvate

        np.random.seed(1)

        mol = Molecule("6VA1")
        smol = solvate(mol)

        tmpdir = os.path.join(self.testDir, "rna", "6VA1")
        _ = build(smol, outdir=tmpdir)

        refdir = home(dataDir=join("test-amber-build", "rna", "6VA1"))
        _TestAmberBuild._compareResultFolders(refdir, tmpdir, "6VA1")

    def test_dna(self):
        from htmd.builder.solvate import solvate

        np.random.seed(1)

        mol = Molecule("1BNA")
        smol = solvate(mol)

        tmpdir = os.path.join(self.testDir, "dna", "1BNA")
        _ = build(smol, outdir=tmpdir)

        refdir = home(dataDir=join("test-amber-build", "dna", "1BNA"))
        _TestAmberBuild._compareResultFolders(refdir, tmpdir, "1BNA")

    def test_protein_rna(self):
        from htmd.builder.solvate import solvate
        from moleculekit.tools.preparation import systemPrepare
        from moleculekit.tools.autosegment import autoSegment

        np.random.seed(1)

        mol = Molecule("3WBM")
        mol.filter("not water")
        mol = autoSegment(mol, field="both")
        pmol = systemPrepare(mol, pH=7.0)
        smol = solvate(pmol)

        tmpdir = os.path.join(self.testDir, "protein-rna", "3WBM")
        _ = build(smol, outdir=tmpdir)

        refdir = home(dataDir=join("test-amber-build", "protein-rna", "3WBM"))
        _TestAmberBuild._compareResultFolders(refdir, tmpdir, "3WBM")

    def test_caps(self):
        from htmd.builder.solvate import solvate
        from moleculekit.tools.preparation import systemPrepare

        np.random.seed(1)

        mol = Molecule("6A5J")
        pmol = systemPrepare(mol, pH=7.0)
        smol = solvate(pmol)

        tmpdir = os.path.join(self.testDir, "peptide-cap", "6A5J")
        _ = build(smol, outdir=tmpdir, ionize=False)

        refdir = home(dataDir=join("test-amber-build", "peptide-cap", "6A5J"))
        _TestAmberBuild._compareResultFolders(refdir, tmpdir, "6A5J")

        np.random.seed(1)

        mol = Molecule("6A5J")
        pmol = systemPrepare(mol, pH=7.0)
        pmol.remove("(resid 1 13 and not backbone) or (resid 13 and name OXT)")
        smol = solvate(pmol)

        tmpdir = os.path.join(self.testDir, "peptide-cap-only-backbone", "6A5J")
        _ = build(smol, outdir=tmpdir, ionize=False)

        refdir = home(
            dataDir=join("test-amber-build", "peptide-cap-only-backbone", "6A5J")
        )

        _TestAmberBuild._compareResultFolders(refdir, tmpdir, "6A5J")

    def test_non_standard_residue_building(self):
        import tempfile

        homedir = home(dataDir=join("test-amber-build", "non-standard"))

        with tempfile.TemporaryDirectory() as outdir:
            pmol = Molecule(os.path.join(homedir, "5VBL_nolig.pdb"))
            _ = build(
                pmol,
                topo=glob(os.path.join(homedir, "*.prepi")),
                param=glob(os.path.join(homedir, "*.frcmod")),
                ionize=False,
                outdir=outdir,
            )
            refdir = home(dataDir=join("test-amber-build", "non-standard", "build"))

            _TestAmberBuild._compareResultFolders(refdir, outdir, "5VBL")


if __name__ == "__main__":
    import doctest
    import unittest

    failure_count, _ = doctest.testmod()
    unittest.main(verbosity=2)
    # if failure_count != 0:
    #     raise Exception('Doctests failed')
