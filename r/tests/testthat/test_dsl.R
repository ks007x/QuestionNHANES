source(file.path("..", "..", "engine", "R", "dsl.R"))

test_that("whitelist blocks dangerous calls", {
  d <- data.frame(a = 1:3)
  expect_error(dsl_eval("system('ls')", d), "not allowed")
  expect_error(dsl_eval("a <- 2", d), "not allowed")
  expect_error(dsl_eval("get('a')", d), "not allowed")
  expect_error(dsl_eval("b + 1", d), "Unknown variable")
})

test_that("cases() assigns first TRUE and keeps level order", {
  d <- data.frame(x = c(5, 12, 30, NA))
  out <- dsl_eval('cases(x < 10, "lo", x < 20, "mid", .default = "hi")', d)
  expect_equal(as.character(out), c("lo", "mid", "hi", NA))
  expect_equal(levels(out), c("lo", "mid", "hi"))
})

test_that("any_of handles missing like a clinical OR", {
  d <- data.frame(a = c(TRUE, FALSE, NA, NA, FALSE), b = c(NA, FALSE, TRUE, NA, NA))
  expect_equal(dsl_eval("any_of(a, b)", d), c(TRUE, FALSE, TRUE, NA, FALSE))
})

test_that("CKD-EPI 2021 matches a worked example", {
  d <- data.frame(creatinine = 1.0, female = 0, age = 50)
  e <- dsl_eval("142 * pmin(creatinine / ifelse(female == 1, 0.7, 0.9), 1)^ifelse(female == 1, -0.241, -0.302) * pmax(creatinine / ifelse(female == 1, 0.7, 0.9), 1)^(-1.2) * 0.9938^age * ifelse(female == 1, 1.012, 1)", d)
  expect_equal(round(e), 92)  # NKF CKD-EPI 2021 calculator: 92
})

test_that("functional iron deficiency definition", {
  d <- data.frame(ferritin = c(20, 50, 50, NA), tsat = c(10, 15, 25, 10))
  expect_equal(dsl_coerce(dsl_eval("ferritin >= 30 & tsat < 20", d), "binary"), c(0L, 1L, 0L, NA))
})
