/*****************************************************************************
 *
 * MODULE:	r.massmov
 *
 * AUTHOR(S):	Original author:
 *              Santiago Begueria (EEAD-CSIC)
 * 		Monia Molinari <monia.molinari supsi.ch>
 * 		Massimiliano Cannata <massimiliano.cannata supsi.ch>
 *		
 *
 * PURPOSE: This module is intended to provide the capability of simulating 
 *          mass movement (fast landslide) over complex topography. This module
 *          applies the Shallow Water Equation (SWE) with different types of 
 *          rheologies (frictional,Voellmy,viscoplastic) 
 *
 *
 * COPYRIGHT:	(C) 2012 by the GRASS Development Team
 *
 *		This program is free software under the GNU General Public
 *		Licence (>=2). Read the file COPYING that cames with GRASS
 *		for details.
 *
 ****************************************************************************/

/* libraries*/
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <grass/gis.h>
#include <grass/raster.h>
#include <grass/glocale.h>
#include "filters.h"
#include "general_f.h"

/* numerical stability control */
#define CFLlimsup  0.5 			/* Higher value of the Courant-Friedrichs-Levy */
#define CFLliminf  0.3			/* Lower value of the Courant-Friedrichs-Levy */
#define MinNLoops  1 			  /* Minimum number of internal loops */
#define MaxNLoops  124 			/* Maximum number of internal loops */
#define InitialLoops  1  		/* Initial number of internal loops */
#define laxfactor  0.5 			/* Low pass filtering for the lax function (0 = no filtering) */
#define dTLeap  0.3 	   		/* Fraction of dT, used for time extrapolation of fluxes */
#define verysmall  0.01 		/* threshold to avoid div by very small values */
#define nullo -999.9f

/* timestep control */
#define dT 1.0              /* Timeslice */

/* other constants */
#define grav 9.8		        /* Gravity acceleration */

/* functions definition  */
#define min(A,B) ((A) < (B) ? (A):(B))
#define max(A,B) ((A) > (B) ? (A):(B))

/*
 * global functions declaration
 */

/*
 * main function
 *
 *
 */

int main(int argc, char *argv[]) {
	struct Cell_head cellhd; /* it stores region information and header information of rasters */
	struct Cell_head window;
	struct History history; /*  holds meta-data */

	/* mapset name locator */
	char *mapset_ELEV;
	char *mapset_HINI;
	char *mapset_DIST;

	/* input buffer */
	FCELL *inrast_ELEV;
	FCELL *inrast_HINI;
	FCELL *inrast_DIST;

	/* output buffer */
	float *outrast_H;
	float *outrast_V;

	/* input file descriptor */
	int infd_ELEV;
	int infd_HINI;
	int infd_DIST;

	/* output file descriptor */
	int outfd_H;
	int outfd_V;

	/* cell counters */
	int row, col;
	int nrows, ncols;
	float res_ns, res_ew, ca;

	/* input & output arguments */
	int TIMESTEPS, DELTAT, RHEOL_TYPE;
	float RHO, YSTRESS, CHEZY, VISCO, BFRICT, IFRICT, FLUID,NS_THRES;
	char RHEOL;
	char name1[20];
	char *name_ELEV;
	char *name_HINI;
	char *name_DIST;
	char *result_H;
	char *result_V;
	char *result_HMAX;
	char *result_VMAX;

	/* memory matrix */
	float **m_ELEV, **m_HINI, **m_DIST;
	int **m_OUTLET;
	float **m_gx, **m_gy, **m_slope;
	float **m_H, **m_Hloop_dt, **m_Hloop, **m_V, **m_Vloop, **m_Vloop_dt, **m_U,
			**m_Uloop, **m_Uloop_dt, **m_HUloop, **m_HVloop, **m_Hold, **m_Hmax, **m_Vmax;
	float **m_K, **m_Kloop, **m_Hland, **TEST;

	/*int variables */

	float elev_fcell_val, dist_fcell_val, hini_fcell_val;
	int outlet_cell_val;

	float gx, gy, slope;
	float k_act, k_pas;
	float G_x, G_y, I_x, I_y, P_x, P_y, T, T_x, T_y, T_x_b, T_y_b, T_b;
	float ddt, dt;
	float Uloop_a, Vloop_a, Uloop_b, Vloop_b, vel, vel_b, Uloop_dt, Vloop_dt, Hloop_a, Hloop_dt, dH_dT, H_fluid;
	float CFL, CFL_u, CFL_v;
	float Vol_gone_loop, Vol_exp_loop, mbe;
	float NS,NSold;
	int testPar;

	/***********************************************************************************************************************/
	/* GRASS structure */
	struct GModule *module;
	struct Option *input_ELEV, *input_HINI,*input_DIST,
			*input_RHEOL, *input_RHO, *input_YSTRESS, *input_CHEZY,
			*input_VISCO, *input_BFRICT, *input_IFRICT, *input_FLUID,
			*input_TIMESTEPS, *input_DELTAT, *output_H, *output_VEL, *input_NS_THRES, *output_HMAX, *output_VMAX;
	struct Flag *flag_i;

	/* initialize GIS environment */
	G_gisinit(argv[0]);

	/* initialize module */
	module = G_define_module();
	G_add_keyword(_("raster"));
	G_add_keyword(_("landslide"));
	G_add_keyword(_("model"));
	module->description =_("Estimation of run-out and deposition of landslide phenomena over a complex topography");

	/* define the different options */

	input_ELEV = G_define_option();
	input_ELEV->key = "elev";
	input_ELEV->type = TYPE_STRING;
	input_ELEV->required = YES;
	input_ELEV->gisprompt = "old,cell,raster";
	input_ELEV->description = _("Name of elevation raster map");
	input_ELEV->guisection = _("Input options");

	input_HINI = G_define_option();
	input_HINI->key = "h_ini";
	input_HINI->type = TYPE_STRING;
	input_HINI->required = YES;
	input_HINI->gisprompt = "old,cell,raster";
	input_HINI->description = _("Name of landslide initial body thickness raster map");
	input_HINI->guisection = _("Input options");

	input_DIST = G_define_option();
	input_DIST->key = "fluiddist";
	input_DIST->type = TYPE_STRING;
	input_DIST->required = YES;
	input_DIST->gisprompt = "old,cell,raster";
	input_DIST->description = _("Name of distance from the landlide toe raster map");
	input_DIST->guisection = _("Input options");

	input_RHEOL = G_define_option();
	input_RHEOL->key = "rheology";
	input_RHEOL->type = TYPE_STRING;
	input_RHEOL->required = YES;
	input_RHEOL->options = "frictional,Voellmy,viscoplastic";
	input_RHEOL->description = _("Name of rheological law");
	input_RHEOL->guisection = _("Input options");

	input_RHO = G_define_option();
	input_RHO->key = "rho";
	input_RHO->type = TYPE_DOUBLE;
	input_RHO->required = NO;
	input_RHO->multiple = NO;
	input_RHO->description =_("Density of the flow [Kg/m3]. Required only for viscous rheologies.");
	input_RHO->guisection = _("Input options");

	input_YSTRESS = G_define_option();
	input_YSTRESS->key = "ystress";
	input_YSTRESS->type = TYPE_DOUBLE;
	input_YSTRESS->required = NO;
	input_YSTRESS->multiple = NO;
	input_YSTRESS->description =_("Apparent yield stress [Pa]. Used only for viscous rheologies (optional).");
	input_YSTRESS->guisection = _("Input options");

	input_VISCO = G_define_option();
	input_VISCO->key = "visco";
	input_VISCO->type = TYPE_DOUBLE;
	input_VISCO->required = NO;
	input_VISCO->multiple = NO;
	input_VISCO->description = _("Dynamic viscosity [Pa*s]. Required only for viscous rheologies");
	input_VISCO->guisection = _("Input options");

	input_CHEZY = G_define_option();
	input_CHEZY->key = "chezy";
	input_CHEZY->type = TYPE_DOUBLE;
	input_CHEZY->required = NO;
	input_CHEZY->multiple = NO;
	input_CHEZY->description =_("Chezy roughness coefficient [m/s2]. Required only for Voellmy rheology");
	input_CHEZY->guisection = _("Input options");

	input_BFRICT = G_define_option();
	input_BFRICT->key = "bfrict";
	input_BFRICT->type = TYPE_DOUBLE;
	input_BFRICT->required = NO;
	input_BFRICT->multiple = NO;
	input_BFRICT->description = _("Angle of basal friction [deg]");
	input_BFRICT->guisection = _("Input options");

	input_IFRICT = G_define_option();
	input_IFRICT->key = "ifrict";
	input_IFRICT->type = TYPE_DOUBLE;
	input_IFRICT->required = YES;
	input_IFRICT->multiple = NO;
	input_IFRICT->description = _("Angle of internal friction [deg]");
	input_IFRICT->guisection = _("Input options");

	input_FLUID = G_define_option();
	input_FLUID->key = "fluid";
	input_FLUID->type = TYPE_DOUBLE;
	input_FLUID->required = YES;
	input_FLUID->multiple = NO;
	input_FLUID->description = _("Upward velocity of transition from solid to fluid of the landsliding mass [m/s]");
	input_FLUID->guisection = _("Input options");

	input_TIMESTEPS = G_define_option();
	input_TIMESTEPS->key = "timesteps";
	input_TIMESTEPS->type = TYPE_INTEGER;
	input_TIMESTEPS->required = YES;
	input_TIMESTEPS->multiple = NO;
	input_TIMESTEPS->description = _(
			"Maximum number of time steps of the simulation [s]");
	input_TIMESTEPS->guisection = _("Input options");

	input_DELTAT = G_define_option();
	input_DELTAT->key = "deltatime";
	input_DELTAT->type = TYPE_INTEGER;
	input_DELTAT->required = NO;
	input_DELTAT->multiple = NO;
	input_DELTAT->description = _("Reporting time frequency [s]");
	input_DELTAT->guisection = _("Input options");

	input_NS_THRES = G_define_option();
	input_NS_THRES->key = "ns_thres";
	input_NS_THRES->type = TYPE_DOUBLE;
	input_NS_THRES->required = NO;
	input_NS_THRES->multiple = NO;
	input_NS_THRES->description = _("Threshold for Nash-Sutcliffe convergence [-]");
	input_NS_THRES->guisection = _("Input options");

	output_H = G_define_option();
	output_H->key = "h";
	output_H->type = TYPE_STRING;
	output_H->required = NO;
	output_H->gisprompt = "new,cell,raster";
	output_H->description = _("Prefix for flow thickness output raster maps");
	output_H->guisection = _("Output options");

	output_HMAX = G_define_option();
	output_HMAX->key = "h_max";
	output_HMAX->type = TYPE_STRING;
	output_HMAX->required = NO;
	output_HMAX->gisprompt = "new,cell,raster";
	output_HMAX->description = _("Prefix for maximum flow thickness output raster maps");
	output_HMAX->guisection = _("Output options");

	output_VEL = G_define_option();
	output_VEL->key = "v";
	output_VEL->type = TYPE_STRING;
	output_VEL->required = NO;
	output_VEL->gisprompt = "new,cell,raster";
	output_VEL->description = _("Prefix for flow velocity output raster maps");
	output_VEL->guisection = _("Output options");

	output_VMAX = G_define_option();
	output_VMAX->key = "v_max";
	output_VMAX->type = TYPE_STRING;
	output_VMAX->required = NO;
	output_VMAX->gisprompt = "new,cell,raster";
	output_VMAX->description = _("Prefix for maximum flow velocity output raster maps");
	output_VMAX->guisection = _("Output options");

    flag_i = G_define_flag();
    flag_i->key = 'i';
    flag_i->description = _("Print input data");

	if (G_parser(argc, argv))
		exit(EXIT_FAILURE);

	/***********************************************************************************************************************/
	/* get entered parameters */

	name_ELEV = input_ELEV->answer;
	name_DIST = input_DIST->answer;
	name_HINI = input_HINI->answer;

	result_H = output_H->answer;
	result_V = output_VEL->answer;
	result_HMAX = output_HMAX->answer;
	result_VMAX = output_VMAX->answer;

	G_debug(1,"Getting numeric input data...");

	if (strcmp(input_RHEOL->answer, "frictional") == 0)
		RHEOL_TYPE = 1;
	if (strcmp(input_RHEOL->answer, "Voellmy") == 0)
		RHEOL_TYPE = 2;
	if (strcmp(input_RHEOL->answer, "viscoplastic") == 0)
		RHEOL_TYPE = 3;


	if (input_RHO->answer)
		sscanf(input_RHO->answer, "%f", &RHO);
	else
		RHO = -1;

	if (input_YSTRESS->answer)
		sscanf(input_YSTRESS->answer, "%f", &YSTRESS);
	else
		YSTRESS = -1;

	if (input_CHEZY->answer)
		sscanf(input_CHEZY->answer, "%f", &CHEZY);
	else
		CHEZY = -1;
	
	if (input_VISCO->answer)
		sscanf(input_VISCO->answer, "%f", &VISCO);
	else
		VISCO = -1;
	
	if (input_BFRICT->answer)
		sscanf(input_BFRICT->answer, "%f", &BFRICT);
	else
		BFRICT = -1;

	if (input_NS_THRES->answer)
		sscanf(input_NS_THRES->answer, "%f", &NS_THRES);
	else
		NS_THRES = -1;

	sscanf(input_IFRICT->answer, "%f", &IFRICT);

	sscanf(input_FLUID->answer, "%f", &FLUID);

	if (input_DELTAT->answer)
		DELTAT = atoi(input_DELTAT->answer);
	else
		DELTAT = -1;

	TIMESTEPS = atoi(input_TIMESTEPS->answer);

	/* check outputs required */
	if (!((result_H) || (result_V) || (result_HMAX) || (result_VMAX))){
		G_fatal_error(_("No output specified"));
	}
	
	/* check rheology parameters */
	testPar = check_rheol_par(RHEOL_TYPE, CHEZY, VISCO, RHO);
	
	if (testPar == -2)
		G_fatal_error(_("For the selected rheology Chezy parameter is required"));
	
	if (testPar == -3)
		G_fatal_error(_("For the selected rheology viscosity and density parameters are required"));
	
	/* report Input Data */
	if (flag_i->answer){
		report_input(IFRICT,RHO, YSTRESS, VISCO, CHEZY, BFRICT,FLUID, NS_THRES, TIMESTEPS, DELTAT);
	}

	G_debug(2,"Verifiyng raster maps input data...");

	/* find maps in mapset */
	mapset_ELEV = (char *) G_find_raster2(name_ELEV, "");
	if (mapset_ELEV == NULL)
		G_fatal_error(_("cell file [%s] not found"), name_ELEV);

	mapset_DIST = (char *) G_find_raster2(name_DIST, "");
	if (mapset_DIST == NULL)
		G_fatal_error(_("cell file [%s] not found"), name_DIST);

	mapset_HINI = (char *) G_find_raster2(name_HINI, "");
	if (mapset_HINI == NULL)
		G_fatal_error(_("cell file [%s] not found"), name_HINI); 

	/* rast_open_old */
	if ((infd_ELEV = Rast_open_old(name_ELEV, mapset_ELEV)) < 0)
		G_fatal_error(_("Cannot open cell file [%s]"), name_ELEV);


	if ((infd_DIST = Rast_open_old(name_DIST, mapset_DIST)) < 0)
		G_fatal_error(_("Cannot open cell file [%s]"), name_DIST);

	if ((infd_HINI = Rast_open_old(name_HINI, mapset_HINI)) < 0)
		G_fatal_error(_("Cannot open cell file [%s]"), name_HINI);


	/* controlling if we can open input raster */
	Rast_get_cellhd(name_ELEV, mapset_ELEV, &cellhd);
	G_debug(3, "number of rows %d", cellhd.rows);

	Rast_get_cellhd(name_DIST, mapset_DIST, &cellhd);
	G_debug(3, "number of rows %d", cellhd.rows);

	Rast_get_cellhd(name_HINI, mapset_HINI, &cellhd); 
	G_debug(3, "number of rows %d", cellhd.rows);


	/* allocate input buffer */
	inrast_ELEV = Rast_allocate_f_buf(); 
	inrast_DIST = Rast_allocate_f_buf();
	inrast_HINI = Rast_allocate_f_buf();

	G_debug(1,"Getting region extension...");

	/* get windows rows & cols */
	nrows = Rast_window_rows();
	ncols = Rast_window_cols();
	G_get_window(&window);
	res_ew = window.ew_res;
	res_ns = window.ns_res;
	ca = res_ns * res_ew;


	G_debug(2,"Allocating memory matrix...");

	/* allocate memory matrix */
	m_ELEV = G_alloc_fmatrix(nrows, ncols);
	m_OUTLET = G_alloc_imatrix(nrows, ncols);
	m_DIST = G_alloc_fmatrix(nrows, ncols);
	m_HINI = G_alloc_fmatrix(nrows, ncols);
	m_gx = G_alloc_fmatrix(nrows, ncols);
	m_gy = G_alloc_fmatrix(nrows, ncols);
	m_slope = G_alloc_fmatrix(nrows, ncols);
	m_U = G_alloc_fmatrix(nrows, ncols);
	m_Uloop = G_alloc_fmatrix(nrows, ncols);
	m_Uloop_dt = G_alloc_fmatrix(nrows, ncols);
	m_V = G_alloc_fmatrix(nrows, ncols);
	m_Vloop = G_alloc_fmatrix(nrows, ncols);
	m_Vloop_dt = G_alloc_fmatrix(nrows, ncols);
	m_H = G_alloc_fmatrix(nrows, ncols);
	m_Hloop = G_alloc_fmatrix(nrows, ncols);
	m_Hloop_dt = G_alloc_fmatrix(nrows, ncols);
	m_Hland = G_alloc_fmatrix(nrows, ncols);
	m_K = G_alloc_fmatrix(nrows, ncols);
	m_Kloop = G_alloc_fmatrix(nrows, ncols);
	m_HUloop = G_alloc_fmatrix(nrows, ncols);
	m_HVloop = G_alloc_fmatrix(nrows, ncols);

	if (NS_THRES!=-1){
		m_Hold= G_alloc_fmatrix(nrows, ncols);
	}

	if (result_HMAX){
		m_Hmax = G_alloc_fmatrix(nrows, ncols);
	}

	if (result_VMAX){
		m_Vmax = G_alloc_fmatrix(nrows, ncols);
	}

	/* read rows */
	G_debug(2,"Reading input maps...");
	for (row = 0; row < nrows; row++) {

		/* read a line input maps into buffers*/
		Rast_get_f_row(infd_ELEV, inrast_ELEV, row);
		Rast_get_f_row(infd_DIST, inrast_DIST, row);
		Rast_get_f_row(infd_HINI, inrast_HINI, row);

		for (col = 0; col < ncols; col++) {
			elev_fcell_val = ((FCELL *) inrast_ELEV)[col];
			dist_fcell_val = ((FCELL *) inrast_DIST)[col];
			hini_fcell_val = ((FCELL *) inrast_HINI)[col];

			/* elevation map */
			if (Rast_is_f_null_value(&elev_fcell_val) == 1) {
				m_ELEV[row][col] = nullo;
			} else {
				m_ELEV[row][col] = ((FCELL *) inrast_ELEV)[col];
			}

			/* distance map */
			if (Rast_is_f_null_value(&dist_fcell_val) == 1) {
				m_DIST[row][col] = nullo;
			} else {
				m_DIST[row][col] = ((FCELL *) inrast_DIST)[col];
			}

			/* hini map */      
			if (Rast_is_f_null_value(&hini_fcell_val) == 1) {
				m_HINI[row][col] = nullo;
			} else {
				m_HINI[row][col] = ((FCELL *) inrast_HINI)[col];
			}

		}
	}

	/* memory cleanup */
	G_free(inrast_ELEV);
	G_free(inrast_DIST);
	G_free(inrast_HINI);

	/* closing raster map */
	Rast_close(infd_ELEV);
	Rast_close(infd_DIST);
	Rast_close(infd_HINI);


	/* earth pressure coefficient */
	k_act = (1 - sin((M_PI * IFRICT) / 180.0))
			/ (1 + sin((M_PI * IFRICT) / 180.0));

	k_pas = (1 + sin((M_PI * IFRICT) / 180.0))
			/ (1 - sin((M_PI * IFRICT) / 180.0));

	G_debug(1,"K_pas value = %f",k_pas);
	G_debug(1,"K_act value = %f",k_act);


	/* inizializzazione matrici in memoria: U,V,H,gx,gz,slope */

	for (row = 0; row < nrows; row++) {
		for (col = 0; col < ncols; col++) {

			m_H[row][col] = 0;
			m_Hloop[row][col] = 0;
			m_Hloop_dt[row][col] = 0;
			m_Hland[row][col] = 0;
			m_U[row][col] = 0;
			m_Uloop[row][col] = 0;
			m_Uloop_dt[row][col] = 0;
			m_V[row][col] = 0;
			m_Vloop[row][col] = 0;
			m_Vloop_dt[row][col] = 0;
			m_K[row][col] = nullo;
			m_gx[row][col] = nullo;
			m_gy[row][col] = nullo;
			m_slope[row][col] = nullo;
			m_HUloop[row][col] = 0;
			m_HVloop[row][col] = 0;
		}
	}

	for (row = 0; row < nrows; row++) {
		for (col = 0; col < ncols; col++) {
			if (row==0 || row==1 || col==0 || col==1 || row==nrows-1 || col==ncols-1 || row==nrows-2 || col==ncols-2)
				m_OUTLET[row][col]=1;
			else
				m_OUTLET[row][col]=0;
		}
	}


	if (NS_THRES!=-1){
		for (row = 0; row < nrows; row++) {
			for (col = 0; col < ncols; col++) {
				m_Hold[row][col] = 0;
			}
		}
	}


	if (result_HMAX){
		for (row = 0; row < nrows; row++) {
			for (col = 0; col < ncols; col++) {
				m_Hmax[row][col] = 0;
			}
		}
	}

	if (result_VMAX){
		for (row = 0; row < nrows; row++) {
			for (col = 0; col < ncols; col++) {
				m_Vmax[row][col] = 0;
			}
		}
	}



   /*---------------------------------------------------------- */
   /* calcolo matrici gx, gy, slope */

	for (row = 1; row < nrows - 1; row++) {
		for (col = 1; col < ncols - 1; col++) {

			gx = gradx2(m_ELEV, row, col, res_ew, 0);
			gy = grady2(m_ELEV, row, col, res_ns, 0);

			/* slope calcolata con Horn 3x3 */
			slope = sqrt(pow(gradx3(m_ELEV, row, col, res_ew, 0), 2) + pow(grady3(m_ELEV, row, col, res_ns, 0), 2));
			m_gx[row][col] = gx;
			m_gy[row][col] = gy;
			m_slope[row][col] = slope;

		}
	}


	/* Starting loops*/
	int t=1;
	int i;
	int loop, n_loops = 1;
	float incr_volexp = 0;
	float Vol_gone=0;
	float Vol_exp=0;
	float Vol_actual=0;
	int NS_count = 0;


	/* while: for each timestep or until NS_count<3 */
    while (NS_count<3 && t<=TIMESTEPS) {
		i = t - 1;

		float CFL_max = 0;
		int stable = 0;

		for (row = 1; row < nrows - 1; row++) {
			for (col = 1; col < ncols - 1; col++) {

				/* Ricalcolo H in funzione di H_fluid e calcolo incremento di Volume aspettato */
				if (m_DIST[row][col] <= i * dT * FLUID
						&& m_DIST[row][col] > (i - 1) * dT * FLUID) {
					H_fluid = m_HINI[row][col];
					m_H[row][col] += H_fluid;
				} else {
					H_fluid = 0.0;
				}
				incr_volexp += H_fluid/(cos(atan(m_slope[row][col])))*ca;


				/* Calcolo Hland */
				if (m_DIST[row][col] > i * dT * FLUID) {
					m_Hland[row][col] = m_HINI[row][col];
				} else {
					m_Hland[row][col] = 0.0;
				}
			}
		}

		G_debug(1,"\nTIMESTEP %i",t);
		G_debug(1,"Volume expected increment = %f",incr_volexp);

		/* ciclo while */
		while (stable==0) {
			int exit = 0;


			G_debug(2,"Updating maps and volumes");

			/* Aggiornamento Hloop,Vloop e Uloop */
			for (row = 1; row < nrows - 1; row++) {
				for (col = 1; col < ncols - 1; col++) {
					m_Hloop[row][col] = m_H[row][col];
					m_Uloop[row][col] = m_U[row][col];
					m_Vloop[row][col] = m_V[row][col];
				}
			}

			/* Aggiornamento Volumi */
			Vol_gone_loop = Vol_gone;
			Vol_exp_loop = Vol_exp;
			Vol_actual = 0;


			/* Per ogni iterazione */
			G_debug(1,"\n---NLOOPS=%i---",n_loops);
			for (loop = 1; loop <= n_loops && exit == 0; loop++) {
				G_debug(1,"\n-LOOP=%i",loop);


				G_debug(2,"Updating K and Kloop matrix");

				for (row = 1; row < nrows - 1; row++) {
					for (col = 1; col < ncols - 1; col++) {
						if ((gradx2(m_Uloop, row, col, res_ew, 0)
								+ grady2(m_Vloop, row, col, res_ns, 0)) >= 0)
							m_K[row][col] = k_act;
						else
							m_K[row][col] = k_pas;
					}
				}


				for (row = 1; row < nrows - 1; row++) {
					for (col = 1; col < ncols - 1; col++) {
						m_Kloop[row][col] = lax(m_K, row, col, laxfactor);
					}
				}


				/* ciclo row-col per calcolare G, P, I, T, Tb */
				G_debug(2,"Calculating G, P, I, T, Tb");

				for (row = 1; row < nrows - 1 && exit == 0; row++) {
					for (col = 1; col < ncols - 1 && exit == 0; col++) {

						/* Calcolo G_x e G_y */

						if (m_Hloop[row][col] > verysmall) {
							G_x = -grav * (sin(atan(m_gx[row][col])));
						} else {
							G_x = 0.0;
						}


						if (m_Hloop[row][col] > verysmall) {
							G_y = -grav * (sin(atan(m_gy[row][col])));
						} else {
							G_y = 0.0;
						}


						/* Calcolo I_x e I_y */

						I_x = -((m_Uloop[row][col] * (cos(atan(m_gx[row][col])))
								* gradx2(m_Uloop, row, col, res_ew, 1))
								+ (m_Vloop[row][col] * (cos(atan(m_gy[row][col])))
										* grady2(m_Uloop, row, col, res_ew, 1)));

						I_y = -((m_Uloop[row][col] * (cos(atan(m_gx[row][col])))
								* gradx2(m_Vloop, row, col, res_ew, 1))
								+ (m_Vloop[row][col] * (cos(atan(m_gy[row][col])))
										* grady2(m_Vloop, row, col, res_ns, 1)));


						/* Calcolo P_x e P_y */

						if (m_Hloop[row][col] > verysmall) {
							P_x = -m_Kloop[row][col] * cos(atan(m_gx[row][col]))
									* gradPx2(m_Hloop, m_Hland, m_gx, row, col,
											res_ew);
						} else {
							P_x = 0.0;
						}

						if (m_Hloop[row][col] > verysmall) {
							P_y = -m_Kloop[row][col] * cos(atan(m_gy[row][col]))
									* gradPy2(m_Hloop, m_Hland, m_gy, row, col,
											res_ns);
						} else {
							P_y = 0.0;
						}


						/* Calcolo T_x e T_y */

						vel = sqrt(
								pow(m_Uloop[row][col], 2)
										+ pow(m_Vloop[row][col], 2));


						if (RHEOL_TYPE == 1) {
							T = t_frict(m_Hloop, row, col, BFRICT);
						}

						if (RHEOL_TYPE == 2) {
							T = t_voellmy(vel, m_Hloop, row, col, BFRICT, CHEZY);
						}

						if (RHEOL_TYPE == 3) {
							T = t_visco(vel, m_Hloop, row, col, BFRICT, RHO, VISCO,
									YSTRESS);
						}

						if (m_Hloop[row][col] > verysmall && vel > verysmall) {
							T_x = fabs(m_Uloop[row][col]) / vel * grav
									* (cos(atan(m_gx[row][col]))) * T;
							T_y = fabs(m_Vloop[row][col]) / vel * grav
									* (cos(atan(m_gy[row][col]))) * T;
						}

						else {
							T_x = grav * (cos(atan(m_gx[row][col]))) * T;
							T_y = grav * (cos(atan(m_gy[row][col]))) * T;
						}


						/* Stima del flusso a t + ddt */
						ddt = dTLeap * dT / n_loops;

						/* Lax su Uloop e Vloop se is_df altrimenti 0 */

						Uloop_a = filter_lax(m_Uloop, row, col, laxfactor, m_Hloop, 0.01, 0.0);
						Vloop_a = filter_lax(m_Vloop, row, col, laxfactor, m_Hloop, 0.01, 0.0);

						/* Calcolo U_loop_b e V_loop_b */

						Uloop_b = veldt(Uloop_a, ddt, G_x, P_x, I_x, T_x);
						Vloop_b = veldt(Vloop_a, ddt, G_y, P_y, I_y, T_y);


						/* Calcolo T_x_b, T_y_b in funzione delle nuove Uloop_b, Vloop_b */

						vel_b = sqrt(pow(Uloop_b, 2) + pow(Vloop_b, 2));


						if (RHEOL_TYPE == 1) {
							T_b = T;
						}

						if (RHEOL_TYPE == 2) {
							T_b = t_voellmy(vel_b, m_Hloop, row, col, BFRICT,
									CHEZY);
						}

						if (RHEOL_TYPE == 3) {
							T_b = t_visco(vel_b, m_Hloop, row, col, BFRICT, RHO,
									VISCO, YSTRESS);
						}


						if (m_Hloop[row][col] > verysmall && vel_b > verysmall) {
							T_x_b = fabs(Uloop_b) / vel_b * grav
									* (cos(atan(m_gx[row][col]))) * T_b;
							T_y_b = fabs(Vloop_b) / vel_b * grav
									* (cos(atan(m_gy[row][col]))) * T_b;
						} else {
							T_x_b = grav * (cos(atan(m_gx[row][col]))) * T_b;
							T_y_b = grav * (cos(atan(m_gy[row][col]))) * T_b;
						}


						/* Stima del flusso a t + dt*/

						dt = dT / n_loops;
						Uloop_dt = veldt(Uloop_a, dt, G_x, P_x, I_x, T_x_b);
						Vloop_dt = veldt(Vloop_a, dt, G_y, P_y, I_y, T_y_b);

						/* Calcolo del valore Courant-Friendrichs-Levy */

						CFL_u = dt * sqrt(2)
								* fabs((cos(atan(m_gx[row][col]))) * Uloop_dt)
								/ res_ew;

						CFL_v = dt * sqrt(2)
								* fabs((cos(atan(m_gy[row][col]))) * Vloop_dt)
								/ res_ns;

						CFL = max(CFL_u,CFL_v);


						if (CFL > CFL_max)
							CFL_max = CFL;

						/*	Verifica della condizione di stabilità */

						if (CFL_max > CFLlimsup && n_loops < MaxNLoops) {
							exit = 1;
							n_loops += 1;
							CFL_max=0;
						} else {
							m_Uloop_dt[row][col] = Uloop_dt;
							m_Vloop_dt[row][col] = Vloop_dt;


							if (m_Hloop[row][col] > verysmall) {
								m_HUloop[row][col] = m_Hloop[row][col] * Uloop_dt;
								m_HVloop[row][col] = m_Hloop[row][col] * Vloop_dt;
							} else {
								m_HUloop[row][col] = 0.0;
								m_HVloop[row][col] = 0.0;
							}
						}
					} /*chiusura FOR cols*/
				} /*chiusura FOR rows*/

				G_debug(2,"CFL_max=%f",CFL_max);

				if (exit==0) {
					G_debug(2,"Calculating Hloop_dt without mbe for loop");

					for (row = 1; row < nrows - 1 && exit == 0; row++) {
						for (col = 1; col < ncols - 1 && exit == 0; col++) {

							/* calcolo dH/dT */
							dH_dT = -cos(atan(m_gx[row][col]))* (shift0(m_HUloop,row,col,nrows-1,ncols-1,1,1,0,-1)-shift0(m_HUloop,row,col,nrows-1,ncols-1,1,1,0,1))/(2*res_ew/cos(atan(m_gx[row][col])))
									-cos(atan(m_gy[row][col]))* (shift0(m_HVloop,row,col,nrows-1,ncols-1,1,1,1,0)-shift0(m_HVloop,row,col,nrows-1,ncols-1,1,1,-1,0))/(2*res_ns/cos(atan(m_gy[row][col])));

							/* Lax su Hloop e calcolo Hloop_dt (senza mbe) */

							if (dH_dT==0) {
								Hloop_a=m_Hloop[row][col];
							} else {
								Hloop_a = filter_lax(m_Hloop, row, col, laxfactor, m_Hloop, 0.01, 0.0);
							}

							Hloop_dt = Hloop_a - dT/n_loops * dH_dT;


							/* Vol_gone_loop */
							Vol_actual += Hloop_dt/(cos(atan(m_slope[row][col])))*ca;
							if (m_OUTLET[row][col]==1){
								/*Vol_gone_no_mbe = Hloop_dt/(cos(atan(m_slope[row][col])))*ca;*/
								Vol_gone_loop += Hloop_dt/(cos(atan(m_slope[row][col])))*ca;
								Hloop_dt = 0.0;
							}

							/* matrice H_loop_dtemp */
							m_Hloop_dt[row][col] = Hloop_dt;

						}/*chiusura FOR col*/
					}/*chiusura FOR row*/


					/* m.b.e */
					G_debug(2,"Calculating mass balance error");

					Vol_exp_loop += incr_volexp/n_loops;

					if (Vol_exp_loop > 0.01) {
						mbe = Vol_actual/Vol_exp_loop;
					} else {
						mbe = 1;
					}

					G_debug(2,"mbe=%f",mbe);
					
					/*Vol_gone_loop += Vol_gone_no_mbe/mbe;*/
					Vol_actual = 0;

					/* Hloop_dt con mbe */
					G_debug(2,"Calculating Hloop_dt with mbe for loop");

					for (row = 1; row < nrows - 1 && exit == 0; row++) {
						for (col = 1; col < ncols - 1 && exit == 0; col++) {
							if (mbe > 0.01){
								m_Hloop_dt[row][col]=m_Hloop_dt[row][col]/mbe;
							}
						}
					}

					/* loop<n_loops */
					if (loop<n_loops) {
						G_debug(2,"loop<n_loops");

						for (row = 1; row < nrows - 1 && exit == 0; row++) {
							for (col = 1; col < ncols - 1 && exit == 0; col++) {
								m_Hloop[row][col]=m_Hloop_dt[row][col];
								m_Uloop[row][col]=m_Uloop_dt[row][col];
								m_Vloop[row][col]=m_Vloop_dt[row][col];
							}
						}
					}

				}/* chiusura IF exit*/

			} /*chiusura FOR loops*/

			if (exit==0) {
				G_debug(2,"FINISH N_LOOPS");


				/*------Nash-Sutcliffe-------*/
				if (NS_THRES!=-1){
					G_debug(1,"Calculating Nash-Sutcliffe value");
					if (t==1){
						NSold = nash_sutcliffe(m_Hold,m_Hloop_dt,nrows, ncols);
					} else {
						NS = nash_sutcliffe(m_Hold,m_Hloop_dt, nrows, ncols);
						G_debug(1,"NS old value=%f",NSold);
						G_debug(1,"NS value=%f",NS);

						if(fabs(NS-NSold) <= NS_THRES){
							NS_count += 1;
						} else {
							NS_count = 0;
						}
						NSold = NS;
					}
					G_debug(1,"NS count=%i",NS_count);
				}
				
				for (row = 1; row < nrows - 1; row++) {
					for (col = 1; col < ncols - 1; col++) {
						m_H[row][col]=m_Hloop_dt[row][col];
						m_U[row][col]=m_Uloop_dt[row][col];
						m_V[row][col]=m_Vloop_dt[row][col];
						if (NS_THRES!=-1){
							m_Hold[row][col]=m_Hloop_dt[row][col];
						}
					}
				}

				if (result_HMAX){
					for (row = 1; row < nrows - 1; row++) {
						for (col = 1; col < ncols - 1; col++) {
							if(m_H[row][col]+m_Hland[row][col] > m_Hmax[row][col])
								m_Hmax[row][col] = m_H[row][col]+m_Hland[row][col];
						}
					}
				}

				if (result_VMAX){
					for (row = 1; row < nrows - 1; row++) {
						for (col = 1; col < ncols - 1; col++) {
							if (m_H[row][col]>verysmall){
								if ((sqrt(pow(m_U[row][col],2)+pow(m_V[row][col],2)))>m_Vmax[row][col]){
									m_Vmax[row][col]=(sqrt(pow(m_U[row][col],2)+pow(m_V[row][col],2)));
								}
							}
						}
					}
				}

				stable=1;
				G_debug(1,"Vol_gone_loop=%f\n",Vol_gone_loop);


				Vol_exp=Vol_exp_loop;
				Vol_gone=Vol_gone_loop;

				incr_volexp=0.0;
				if (CFL_max<=CFLliminf) {
					n_loops=max(n_loops-1,MinNLoops);
				}

				/*------- DEFAULT OUTPUT SERIES--------*/

				if((DELTAT!=-1 && t%DELTAT==0) || (t==TIMESTEPS) || (NS_count==3)){

					if(result_H){
						sprintf(name1,"%s_t%d",result_H,t);
						out_sum_print(m_Hland,m_H,m_U,m_V,name1,nrows,ncols,1,0.01);
						Rast_short_history(name1, "raster", &history);
						Rast_command_history(&history);
						Rast_write_history(name1, &history);
					}
					if(result_V){
						sprintf(name1,"%s_t%d",result_V,t);
						out_sum_print(m_Hland,m_H,m_U,m_V,name1,nrows,ncols,2,0.01);
						Rast_short_history(name1, "raster", &history);
						Rast_command_history(&history);
						Rast_write_history(name1, &history);
					}
				}


				if((result_HMAX) && ((t==TIMESTEPS) || (NS_count==3))){
					sprintf(name1,"%s",result_HMAX);
					out_print(m_Hmax,name1,nrows,ncols);
					Rast_short_history(name1, "raster", &history);
					Rast_command_history(&history);
					Rast_write_history(name1, &history);
				}

				if((result_VMAX) && ((t==TIMESTEPS) || (NS_count==3))){
					sprintf(name1,"%s",result_VMAX);
					out_print(m_Vmax,name1,nrows,ncols);
					Rast_short_history(name1, "raster", &history);
					Rast_command_history(&history);
					Rast_write_history(name1, &history);
				}


			} /*chiusura IF exit*/
		} /*chiusura WHILE*/
		t++;
	} /* chiusura WHILE NS_count*/

	if (Vol_gone>0){
		G_warning("The flow is out of the current computational domain. You may need to change the region extension.");
		G_warning("Volume gone: %f",Vol_gone);
	}


	/* deallocate memory matrix */
	G_free_fmatrix(m_ELEV);
	G_free_imatrix(m_OUTLET);
	G_free_fmatrix(m_DIST);
	G_free_fmatrix(m_HINI);
	G_free_fmatrix(m_gx);
	G_free_fmatrix(m_gy);
	G_free_fmatrix(m_slope);
	G_free_fmatrix(m_H);
	G_free_fmatrix(m_Hloop);
	G_free_fmatrix(m_Hloop_dt);
	G_free_fmatrix(m_Hland);
	G_free_fmatrix(m_U);
	G_free_fmatrix(m_Uloop);
	G_free_fmatrix(m_Uloop_dt);
	G_free_fmatrix(m_V);
	G_free_fmatrix(m_Vloop);
	G_free_fmatrix(m_Vloop_dt);
	G_free_fmatrix(m_K);
	G_free_fmatrix(m_Kloop);
	G_free_fmatrix(m_HUloop);
	G_free_fmatrix(m_HVloop);

	if (NS_THRES!=-1)
		G_free_fmatrix(m_Hold);

	if (result_VMAX)
		G_free_fmatrix(m_Vmax);

	if (result_HMAX)
		G_free_fmatrix(m_Hmax);
		
	exit(EXIT_SUCCESS);
}
