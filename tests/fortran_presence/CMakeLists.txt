cmake_minimum_required(VERSION 3.20)
project(array_presence_conformance LANGUAGES Fortran)

set(CMAKE_Fortran_STANDARD 2008)
set(CMAKE_Fortran_STANDARD_REQUIRED ON)

add_executable(array_presence_conformance
  conformance.f90
  out/nml_helper.f90
  out/nml_presence.f90
  out/nml_records.f90
  out/nml_required.f90
  out/nml_long.f90
)
