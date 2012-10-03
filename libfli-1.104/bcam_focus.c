#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "libfli.h"

flidomain_t domain;
flidev_t dev;

int main(int argc, char *argv[]) {

  int err;
  char *model;
  long position;
  long extent, new, delta;
  
  double T_int;

  if (argc < 2) {
    printf("Usage: bcam_focus <position>\n");
    exit(1);
  }

  model = (char *)malloc(256);
  domain = FLIDOMAIN_USB | FLIDEVICE_FOCUSER;

  /* take new stepper position as the one argument */
  new = atol(argv[1]);

  /* open device. need fliusb.ko to be loaded first. */
  err = FLIOpen(&dev, "/dev/fliusb0", domain);
  if (err != 0) {
    printf("Error opening FLI device: %s\n", strerror((int)-err));
    exit(1);
  }

  /* get the model string */
  err = FLIGetModel(dev, model, 256);
  if (err != 0) {
    printf("Error querying FLI model: %s\n", strerror((int)-err));
    exit(1);
  } else {
    printf("FLI model: %s\n", model);
  }

  /* get current stepper position */
  err = FLIGetStepperPosition(dev, &position);
  if (err != 0) {
    printf("Error querying FLI stepper position: %s\n", strerror((int)-err));
    exit(1);
  } else {
    printf("FLI stepper position: %ld\n", position);
  }

  /* get maximum stepper position */
  err = FLIGetFocuserExtent(dev, &extent);
  if (err != 0) {
    printf("Error querying FLI maximum stepper position: %s\n", 
	   strerror((int)-err));
    exit(1);
  } else {
    printf("FLI maximum stepper position: %ld\n", extent);  
  }

  /* sanity check for input value */
  
  if (new < 0 || new > extent) {
    printf("Need to specify focuser position between 0 and %ld.\n", extent);
    exit(1);
  }

  /* get focuser internal temperature */
  err = FLIReadTemperature(dev, FLI_TEMPERATURE_INTERNAL, &T_int);
  if (err != 0) {
    printf("Error querying FLI internal temperature: %s\n", 
	   strerror((int)-err));
    exit(1);
  } else {
    printf("FLI T_int: %.2f\n", T_int);  
  }

  /* now get down to bidness */
  printf("\n");

  delta = new - position;

  printf("Moving %ld steps...\n", delta);

  /* command the motor to step */
  err = FLIStepMotor(dev, delta);
  if (err != 0) {
    printf("Error commanding FLI motor: %s\n", strerror((int)-err));
    exit(1);
  } 

  /* check our work... */    
  /* get current stepper position */
  err = FLIGetStepperPosition(dev, &position);
  if (err != 0) {
    printf("Error querying FLI stepper position: %s\n", strerror((int)-err));
    exit(1);
  } else {
    printf("FLI stepper position: %ld\n", position);
  }

  return 0; 
}
