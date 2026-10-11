suppressPackageStartupMessages(library(survey))
`%||%` <- function(a, b) if (is.null(a)) b else a
source(file.path("..", "..", "engine", "R", "models.R"))

mk <- function(n = 400) {
  set.seed(1)
  d <- data.frame(psu = rep(1:2, n / 2), strata = rep(1:4, each = n / 4), w = runif(n, 1, 3),
                  y = rbinom(n, 1, 0.2), age = rnorm(n, 50, 10),
                  x = factor(sample(c("Control", "A", "B"), n, TRUE), levels = c("Control", "A", "B")),
                  smk = factor(rep("Never", n), levels = c("Never", "Former", "Current")))
  svydesign(ids = ~psu, strata = ~strata, weights = ~w, nest = TRUE, data = d)
}

test_that("a covariate with one value is dropped instead of crashing", {
  des <- mk()
  p <- .prepare_terms(des, "y", c("x", "age", "smk"), "x")
  expect_equal(p$terms, c("x", "age"))
  expect_true(any(grepl("Dropped covariate 'smk'", p$notes)))
})

test_that("an exposure with one value is reported as not estimable", {
  des <- mk(); des$variables$x <- factor(rep("Control", nrow(des$variables)), levels = c("Control", "A", "B"))
  p <- .prepare_terms(des, "y", c("x", "age"), "x")
  expect_null(p$terms)
  expect_true(any(grepl("NOT ESTIMABLE", p$notes)))
})

test_that("empty exposure levels are removed", {
  des <- mk(); v <- as.character(des$variables$x); v[v == "B"] <- "A"
  des$variables$x <- factor(v, levels = c("Control", "A", "B"))
  p <- .prepare_terms(des, "y", c("x", "age"), "x")
  expect_equal(levels(p$design$variables$x), c("Control", "A"))
})

test_that("product terms (x:modifier) are kept so interaction tests run", {
  des <- mk(); des$variables$sex <- factor(rep(c("M", "F"), length.out = nrow(des$variables)))
  p <- .prepare_terms(des, "y", c("age", "sex", "age:sex"), "age")
  expect_equal(p$terms, c("age", "sex", "age:sex"))
  expect_equal(sum(.model_rows(des, c("y", "age:sex"))), nrow(des$variables))
  p2 <- .prepare_terms(des, "y", c("age", "smk", "age:smk"), "age")   # smk is constant -> its product term goes too
  expect_equal(p2$terms, "age")
})
