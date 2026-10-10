library(testthat)
setwd(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))), "testthat"))
test_dir(".", reporter = "summary", stop_on_failure = TRUE)
