import math
import numpy as np
import pandas as pd
from collections import Counter
from functools import lru_cache
from itertools import product as cartesian_product, combinations
from pgmpy.factors.discrete import TabularCPD
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.sampling import BayesianModelSampling


def _calculate_entropy_core(data_df_to_use, var_names_list):
    if not var_names_list:
        return 0.0
    probs, _ = get_probs(data_df_to_use, var_names_list)
    return entropy_from_probs(probs)


@lru_cache(maxsize=None)
def _get_entropy_from_global_df_cached(var_names_tuple):
    if current_data_df_for_caching is None:
        raise ValueError(
            'current_data_df_for_caching is not set. Call set_global_df_for_caching().'
            )
    return _calculate_entropy_core(current_data_df_for_caching, list(
        var_names_tuple))


def bootstrap_hv_values(data_df, target_name, S_names_list, n_boot=100):
    if not S_names_list:
        return np.zeros(n_boot)
    n_samples_in_df = len(data_df)
    hv_samples_list = []
    dl_s = calculate_dl(S_names_list)
    if dl_s == 0:
        return np.zeros(n_boot)
    original_global_df_ref = current_data_df_for_caching
    for i in range(n_boot):
        idx = np.random.choice(n_samples_in_df, n_samples_in_df, replace=True)
        df_boot = data_df.iloc[idx]
        set_global_df_for_caching(df_boot)
        _get_entropy_from_global_df_cached.cache_clear()
        i_t_s_boot = get_joint_mi_with_target(df_boot, target_name,
            S_names_list)
        hv_samples_list.append(i_t_s_boot / dl_s)
    set_global_df_for_caching(original_global_df_ref)
    _get_entropy_from_global_df_cached.cache_clear()
    return np.array(hv_samples_list)


def brute_force_hv_optimal(data_df, target_name, candidate_vars):
    best_set, best_hv = set(), 0.0
    cand_list = list(candidate_vars)
    for r in range(1, len(cand_list) + 1):
        for subset in combinations(cand_list, r):
            mi = get_joint_mi_with_target(data_df, target_name, subset)
            dl = calculate_dl(subset)
            hv = mi / dl if dl else 0.0
            if hv > best_hv + 1e-09:
                best_hv, best_set = hv, set(subset)
    return best_set


def calculate_dl(S_names_list, method='count'):
    if method == 'count':
        return len(S_names_list)
    return len(S_names_list)


def conditional_mutual_information(data_df, X_name, T_name, S_names_list):
    if isinstance(S_names_list, str):
        S_names_list = [S_names_list]
    s_set = set(S_names_list)
    h_x_s_vars = sorted(list(set([X_name]) | s_set))
    h_t_s_vars = sorted(list(set([T_name]) | s_set))
    h_s_vars = sorted(list(s_set))
    h_x_t_s_vars = sorted(list(set([X_name, T_name]) | s_set))
    h_x_s = get_entropy(data_df, h_x_s_vars)
    h_t_s = get_entropy(data_df, h_t_s_vars)
    h_s = get_entropy(data_df, h_s_vars)
    h_x_t_s = get_entropy(data_df, h_x_t_s_vars)
    cmi = h_x_s + h_t_s - h_s - h_x_t_s
    return max(0, cmi)


def define_scenario_1():
    model = DiscreteBayesianNetwork([('X1', 'T'), ('X2', 'T'), ('T', 'Y1'),
        ('X3', 'Y1')])
    nodes_in_scenario = ['X1', 'X2', 'X3', 'X4', 'T', 'Y1']
    for node_name in nodes_in_scenario:
        if node_name not in model.nodes():
            model.add_node(node_name)
    cpd_x1 = TabularCPD('X1', 2, [[0.6], [0.4]])
    cpd_x2 = TabularCPD('X2', 2, [[0.7], [0.3]])
    cpd_x3 = TabularCPD('X3', 2, [[0.5], [0.5]])
    cpd_x4 = TabularCPD('X4', 2, [[0.8], [0.2]])
    cpd_t = TabularCPD('T', 2, [[0.9, 0.6, 0.5, 0.1], [0.1, 0.4, 0.5, 0.9]],
        evidence=['X1', 'X2'], evidence_card=[2, 2])
    cpd_y1 = TabularCPD('Y1', 2, [[0.8, 0.5, 0.6, 0.2], [0.2, 0.5, 0.4, 0.8
        ]], evidence=['T', 'X3'], evidence_card=[2, 2])
    model.add_cpds(cpd_x1, cpd_x2, cpd_x3, cpd_x4, cpd_t, cpd_y1)
    assert model.check_model()
    return model, 'T', nodes_in_scenario


def define_scenario_2():
    model = DiscreteBayesianNetwork([('U', 'X1'), ('U', 'X2'), ('X1', 'T'),
        ('X2', 'T'), ('T', 'Y'), ('U', 'Y')])
    cpd_u = TabularCPD('U', 2, [[0.5], [0.5]])
    cpd_x1 = TabularCPD('X1', 2, [[0.9, 0.1], [0.1, 0.9]], evidence=['U'],
        evidence_card=[2])
    cpd_x2 = TabularCPD('X2', 2, [[0.8, 0.2], [0.2, 0.8]], evidence=['U'],
        evidence_card=[2])
    cpd_t = TabularCPD('T', 2, [[0.9, 0.4, 0.3, 0.05], [0.1, 0.6, 0.7, 0.95
        ]], evidence=['X1', 'X2'], evidence_card=[2, 2])
    cpd_y = TabularCPD('Y', 2, [[0.7, 0.6, 0.4, 0.2], [0.3, 0.4, 0.6, 0.8]],
        evidence=['T', 'U'], evidence_card=[2, 2])
    model.add_cpds(cpd_u, cpd_x1, cpd_x2, cpd_t, cpd_y)
    assert model.check_model()
    return model, 'T', ['U', 'X1', 'X2', 'T', 'Y']


def define_scenario_3():
    model = DiscreteBayesianNetwork([('A', 'M1'), ('M1', 'T'), ('B', 'M2'),
        ('M2', 'T')])
    nodes_in_scenario = ['A', 'B', 'C', 'M1', 'M2', 'T']
    for node_name in nodes_in_scenario:
        if node_name not in model.nodes():
            model.add_node(node_name)
    cpd_a = TabularCPD('A', 2, [[0.5], [0.5]])
    cpd_b = TabularCPD('B', 2, [[0.5], [0.5]])
    cpd_c = TabularCPD('C', 2, [[0.5], [0.5]])
    cpd_m1 = TabularCPD('M1', 2, [[0.8, 0.2], [0.2, 0.8]], evidence=['A'],
        evidence_card=[2])
    cpd_m2 = TabularCPD('M2', 2, [[0.7, 0.3], [0.3, 0.7]], evidence=['B'],
        evidence_card=[2])
    cpd_t = TabularCPD('T', 2, [[0.9, 0.6, 0.5, 0.1], [0.1, 0.4, 0.5, 0.9]],
        evidence=['M1', 'M2'], evidence_card=[2, 2])
    model.add_cpds(cpd_a, cpd_b, cpd_c, cpd_m1, cpd_m2, cpd_t)
    assert model.check_model()
    return model, 'T', nodes_in_scenario


def entropy_from_probs(probs):
    if not probs:
        return 0.0
    p_values = np.fromiter((v for v in probs.values() if v > 0), dtype=float)
    if p_values.size == 0:
        return 0.0
    return -np.sum(p_values * np.log2(p_values))


def get_entropy(data_df, var_names):
    if not var_names:
        return 0.0
    if isinstance(var_names, str):
        var_names = [var_names]
    var_names_tuple = tuple(sorted(var_names))
    if (current_data_df_for_caching is not None and data_df is
        current_data_df_for_caching):
        return _get_entropy_from_global_df_cached(var_names_tuple)
    else:
        return _calculate_entropy_core(data_df, list(var_names_tuple))


def get_joint_mi_with_target(data_df, target_name, S_list):
    if not S_list:
        return 0.0
    h_t = get_entropy(data_df, [target_name])
    h_s = get_entropy(data_df, list(S_list))
    h_t_s = get_entropy(data_df, [target_name] + list(S_list))
    return max(0, h_t + h_s - h_t_s)


def get_probs(data_df, var_names):
    if not var_names:
        return {}, 0
    if isinstance(var_names, str):
        var_names = [var_names]
    elif not isinstance(var_names, list):
        var_names = list(var_names)
    counts = Counter(map(tuple, data_df[var_names].values))
    total_samples = len(data_df)
    probs = {state: (count / total_samples) for state, count in counts.items()}
    return probs, total_samples


def mutual_information(data_df, X_name, T_name):
    h_x = get_entropy(data_df, [X_name])
    h_t = get_entropy(data_df, [T_name])
    h_x_t = get_entropy(data_df, [X_name, T_name])
    mi = h_x + h_t - h_x_t
    return max(0, mi)


def set_global_df_for_caching(data_df):
    global current_data_df_for_caching
    current_data_df_for_caching = data_df
    _get_entropy_from_global_df_cached.cache_clear()


def validate_bootstrap_robustness(data_df, target_name, S_optimal_names,
    hv_s_optimal, all_var_names, results_log, n_boot=100,
    dominance_threshold=0.95):
    results_log.append(
        f'\n--- Validating Corollary 5: Bootstrap Robustness (n_boot={n_boot}) ---'
        )
    results_log.append(
        f'   Mathematical Statement: P_bootstrap(HV(S*) > HV(S~)) ≥ {dominance_threshold * 100:.0f}%'
        )
    hv_opt_samples = bootstrap_hv_values(data_df, target_name, list(
        S_optimal_names), n_boot)
    rejected_vars = [v for v in all_var_names if v not in S_optimal_names and
        v != target_name]
    if not rejected_vars:
        results_log.append(
            '  No rejected variables to form a perturbed set S~. Robustness test cannot be performed or is vacuously true.'
            )
        return True
    S_tilde = list(S_optimal_names) + [rejected_vars[0]]
    results_log.append(f'  Comparing S* with S~ = S* ∪ {{{rejected_vars[0]}}}')
    hv_tilde_samples = bootstrap_hv_values(data_df, target_name, S_tilde,
        n_boot)
    dominance_count = np.sum(hv_opt_samples > hv_tilde_samples)
    dominance_ratio = dominance_count / n_boot if n_boot > 0 else 0.0
    supported = dominance_ratio >= dominance_threshold
    results_log.append(
        f"  HV(S*) > HV(S~) in {dominance_ratio * 100:.1f}% of {n_boot} bootstrap resamples ({dominance_count}/{n_boot}) ({'PASS' if supported else 'FAIL'})"
        )
    results_log.append(
        f'    Mean HV(S*): {np.mean(hv_opt_samples):.4f} (std: {np.std(hv_opt_samples):.4f}), Mean HV(S~): {np.mean(hv_tilde_samples):.4f} (std: {np.std(hv_tilde_samples):.4f})'
        )
    return supported


def validate_hv_score_and_perturbation_fragility(data_df, target_name,
    S_optimal_names, all_var_names, results_log):
    results_log.append(
        f"""
--- Validating Corollary 2 (HV Score Maximization) & Perturbation Fragility ---"""
        )
    results_log.append(
        f'   Mathematical Statement (Cor 2): S* = argmax_S HV(S) where HV(S) = I(T;S)/DL(S)'
        )
    results_log.append(
        f'   Mathematical Statement (Fragility): ∀S~ ≠ S*, HV(S~) < HV(S*)')
    results_log.append(
        f'Optimal set S* (from Rule 1 & 2) = {sorted(list(S_optimal_names))}')
    if not S_optimal_names:
        i_t_s_optimal = 0.0
        dl_s_optimal = 0
        hv_s_optimal = 0.0
        results_log.append(
            f'  S* is empty. I(T;S*) = 0, DL(S*) = 0, HV(S*) = 0 (by convention).'
            )
    else:
        i_t_s_optimal = get_joint_mi_with_target(data_df, target_name,
            S_optimal_names)
        dl_s_optimal = calculate_dl(list(S_optimal_names))
        hv_s_optimal = (i_t_s_optimal / dl_s_optimal if dl_s_optimal > 0 else
            0.0)
    results_log.append(f'  I({target_name}; S*) = {i_t_s_optimal:.4f}')
    results_log.append(f'  DL(S*) = {dl_s_optimal}')
    results_log.append(f'  HV(S*) = {hv_s_optimal:.4f}')
    perturbations_passed = 0
    num_perturbations_tested = 0
    vars_to_add = [v for v in all_var_names if v not in S_optimal_names and
        v != target_name]
    for x_add in vars_to_add:
        num_perturbations_tested += 1
        S_tilde = list(S_optimal_names) + [x_add]
        i_t_s_tilde = get_joint_mi_with_target(data_df, target_name, S_tilde)
        dl_s_tilde = calculate_dl(S_tilde)
        hv_s_tilde = i_t_s_tilde / dl_s_tilde if dl_s_tilde > 0 else 0.0
        passed = (hv_s_tilde < hv_s_optimal if hv_s_optimal > 1e-09 else 
            hv_s_tilde <= hv_s_optimal)
        if passed:
            perturbations_passed += 1
        results_log.append(
            f'  Perturbation (Add {x_add}): S~ = {sorted(S_tilde)}')
        results_log.append(
            f"    I(T;S~)={i_t_s_tilde:.4f}, DL(S~)={dl_s_tilde}, HV(S~)={hv_s_tilde:.4f} ({'PASS' if passed else 'FAIL'})"
            )
    if len(S_optimal_names) > 0:
        for x_del in S_optimal_names:
            num_perturbations_tested += 1
            S_tilde = [v for v in S_optimal_names if v != x_del]
            i_t_s_tilde = get_joint_mi_with_target(data_df, target_name,
                S_tilde)
            dl_s_tilde = calculate_dl(S_tilde)
            hv_s_tilde = i_t_s_tilde / dl_s_tilde if dl_s_tilde > 0 else 0.0
            passed = (hv_s_tilde < hv_s_optimal if hv_s_optimal > 1e-09 else
                hv_s_tilde <= hv_s_optimal)
            if passed:
                perturbations_passed += 1
            results_log.append(
                f'  Perturbation (Del {x_del}): S~ = {sorted(S_tilde)}')
            results_log.append(
                f"    I(T;S~)={i_t_s_tilde:.4f}, DL(S~)={dl_s_tilde}, HV(S~)={hv_s_tilde:.4f} ({'PASS' if passed else 'FAIL'})"
                )
    all_perturbations_support = (perturbations_passed ==
        num_perturbations_tested if num_perturbations_tested > 0 else True)
    results_log.append(
        f"Corollary 2 & Perturbation Fragility Conclusion: {'Supported' if all_perturbations_support else 'Partially Supported/Check FAILs'}. ({perturbations_passed}/{num_perturbations_tested} perturbations lowered HV score)."
        )
    return all_perturbations_support, hv_s_optimal


def validate_informational_necessity_and_redundancy_pruning(data_df,
    target_name, initial_S_names, tau, results_log):
    results_log.append(
        f"""
--- Validating Proposition 2 & Corollary 1: Informational Necessity & Redundancy Pruning (Target: {target_name}) ---"""
        )
    results_log.append(
        f'   Mathematical Statement (Rule 2): X ∈ S_final iff X ∈ S_initial ∧ I(X;T|S_initial\\{{X}}) > τ'
        )
    results_log.append(
        f'   Mathematical Statement (Cor 1): I(T;S_initial) - I(T;S_initial\\{{X_pruned}}) = I(X_pruned;T|S_initial\\{{X_pruned}})'
        )
    results_log.append(
        f'Initial set S = {sorted(list(initial_S_names))}, Tau = {tau}')
    if not initial_S_names:
        results_log.append('Initial set S is empty. Skipping.')
        return set(), True
    S_prime = set(initial_S_names)
    pruned_vars_info = []
    vars_to_check = list(initial_S_names)
    for x_var in vars_to_check:
        if x_var not in S_prime:
            continue
        condition_set = list(S_prime - {x_var})
        cmi_val = conditional_mutual_information(data_df, x_var,
            target_name, condition_set)
        if cmi_val <= tau:
            S_prime.remove(x_var)
            pruned_vars_info.append({'var': x_var, 'cmi': cmi_val, 'action':
                'Pruned'})
            results_log.append(
                f"  I({x_var}; {target_name} | {sorted(condition_set) or 'emptyset'}) = {cmi_val:.4f} <= {tau}. Pruning {x_var}."
                )
            results_log.append(
                f'    Corollary 1 check: Drop in I(T;S_initial_state) by pruning {x_var} should be approx {cmi_val:.4f}.'
                )
        else:
            pruned_vars_info.append({'var': x_var, 'cmi': cmi_val, 'action':
                'Kept'})
            results_log.append(
                f"  I({x_var}; {target_name} | {sorted(condition_set) or 'emptyset'}) = {cmi_val:.4f} > {tau}. Keeping {x_var}."
                )
    results_log.append(f"Final S' after pruning: {sorted(list(S_prime))}")
    sum_cmi_pruned = sum(p['cmi'] for p in pruned_vars_info if p['action'] ==
        'Pruned')
    results_log.append(
        f'Sum of CMIs of pruned variables (expected total drop in I(T;S_initial) if pruning one by one): ~{sum_cmi_pruned:.4f}'
        )
    results_log.append(
        f"Proposition 2 & Corollary 1 Conclusion: Processed. Final set S' derived. Corollary 1 implies that predictive power I(T;S) decreases by the CMI of each pruned variable."
        )
    return S_prime, True


def validate_minimal_causal_sufficiency(model, data_df, target_name,
    all_var_names, results_log):
    results_log.append(
        f"""
--- Validating Proposition 1: Minimal Causal Sufficiency (Target: {target_name}) ---"""
        )
    results_log.append(
        '   Mathematical Statement: S = MB(T) iff (∀X ∈ S, I(X;T|S\\{X}) > 0) ∧ (∀Y ∉ S, I(Y;T|S) ≈ 0)'
        )
    true_mb = set(model.get_markov_blanket(target_name))
    results_log.append(
        f'True Markov Blanket MB({target_name}) from graph: {sorted(list(true_mb))}'
        )
    supported = True
    results_log.append(
        f'\nChecking I(X; {target_name} | MB\\{{X}}) > 0 for X in MB({target_name}):'
        )
    if not true_mb:
        results_log.append(
            'Markov Blanket is empty. Skipping this part of validation.')
    else:
        for x_var in true_mb:
            condition_set = list(true_mb - {x_var})
            cmi = conditional_mutual_information(data_df, x_var,
                target_name, condition_set)
            results_log.append(
                f"  I({x_var}; {target_name} | {sorted(condition_set) or 'emptyset'}) = {cmi:.4f}"
                )
            if not cmi > 0.001:
                results_log.append(
                    f'  WARN: CMI for {x_var} is close to zero. Expected > 0.')
                supported = False
    vars_outside_mb = [v for v in all_var_names if v not in true_mb and v !=
        target_name]
    results_log.append(
        f'\nChecking I(Y; {target_name} | MB) ≈ 0 for Y not in MB({target_name}):'
        )
    if not vars_outside_mb:
        results_log.append('No variables outside MB to test.')
    else:
        for y_var_out in vars_outside_mb:
            cmi = conditional_mutual_information(data_df, y_var_out,
                target_name, list(true_mb))
            results_log.append(
                f"  I({y_var_out}; {target_name} | {sorted(list(true_mb)) or 'emptyset'}) = {cmi:.4f}"
                )
            if cmi > 0.001:
                results_log.append(
                    f'  WARN: CMI for {y_var_out} (outside MB) is NOT close to zero. Expected ≈0.'
                    )
                supported = False
    results_log.append(
        f"Proposition 1 Conclusion: {'Supported' if supported else 'Partially Supported/Check WARNs'}"
        )
    return true_mb, supported


def validate_superset_penalty(data_df, target_name, S_optimal_names,
    hv_s_optimal, all_var_names, results_log):
    results_log.append(f'\n--- Validating Corollary 4: Superset Penalty ---')
    results_log.append(f'   Mathematical Statement: ∀S~ ⊃ S*, HV(S~) < HV(S*)')
    results_log.append(
        f'   (S* = {sorted(list(S_optimal_names))}, HV(S*) = {hv_s_optimal:.4f})'
        )
    violations = 0
    num_supersets_tested = 0
    vars_to_form_supersets = [v for v in all_var_names if v not in
        S_optimal_names and v != target_name]
    if not vars_to_form_supersets and not S_optimal_names:
        results_log.append(
            '  No variables available to form strict supersets of S*, or S* is already maximal/empty. Skipping.'
            )
        return True
    if not vars_to_form_supersets and S_optimal_names:
        results_log.append(
            f'  S* ({sorted(list(S_optimal_names))}) already contains all other relevant variables. No strict supersets to form by adding one variable.'
            )
        return True
    for x_add in vars_to_form_supersets:
        num_supersets_tested += 1
        S_super = list(S_optimal_names) + [x_add]
        i_t_s_super = get_joint_mi_with_target(data_df, target_name, S_super)
        dl_s_super = calculate_dl(S_super)
        hv_s_super = i_t_s_super / dl_s_super if dl_s_super > 0 else 0.0
        passed = (hv_s_super < hv_s_optimal if hv_s_optimal > 1e-09 else 
            hv_s_super <= hv_s_optimal)
        if not passed:
            violations += 1
        results_log.append(
            f"  Superset S~ = S* ∪ {{{x_add}}}: HV(S~) = {hv_s_super:.4f}  ({'PASS' if passed else 'FAIL'})"
            )
    if num_supersets_tested == 0:
        results_log.append(
            '  No supersets were tested (e.g. S_optimal_names contained all_var_names).'
            )
        return True
    supported = violations == 0
    results_log.append(
        f"Corollary 4 Conclusion: {'Supported' if supported else f'FAIL – {violations} violation(s)'}"
        )
    return supported


current_data_df_for_caching = None
if __name__ == '__main__':
    num_samples = 100000
    tau_threshold = 0.02
    n_bootstrap_samples = 1000
    scenarios = {'Scenario 1 (Basic MB)': define_scenario_1,
        'Scenario 2 (Redundancy & Spouses)': define_scenario_2,
        'Scenario 3 (Simple Collider Structure)': define_scenario_3}
    overall_summary = {}
    for scenario_name, scenario_fn in scenarios.items():
        print(f"\n\n{'=' * 20} Running {scenario_name} {'=' * 20}")
        results_log = [f'Results for {scenario_name}:']
        model, target_name, all_var_names = scenario_fn()
        sampler = BayesianModelSampling(model)
        data_df = sampler.forward_sample(size=num_samples)
        set_global_df_for_caching(data_df)
        results_log.append(f'Generated {num_samples} samples.')
        true_mb_names, p1_supported = validate_minimal_causal_sufficiency(model
            , data_df, target_name, all_var_names, results_log)
        overall_summary.setdefault(scenario_name, {})[
            'Prop1: MinCausalSufficiency'
            ] = 'Supported' if p1_supported else 'Check WARNs'
        S_after_pruning, p2_c1_supported = (
            validate_informational_necessity_and_redundancy_pruning(data_df,
            target_name, true_mb_names, tau_threshold, results_log))
        overall_summary.setdefault(scenario_name, {})[
            'Prop2&Cor1: InfoNecessity'] = 'Processed'
        results_log.append(
            f'\n--- Proposition 3: Complexity Penalty (DL(S)) ---')
        results_log.append(
            f'   DL(S) is implemented as count of variables in S. This is used in HV score calculation.'
            )
        overall_summary.setdefault(scenario_name, {})[
            'Prop3: ComplexityPenalty'] = 'Definition (used in HV)'
        S_hv_optimal = brute_force_hv_optimal(data_df, target_name,
            S_after_pruning)
        c2_pf_supported, hv_S_optimal = (
            validate_hv_score_and_perturbation_fragility(data_df,
            target_name, S_hv_optimal, all_var_names, results_log))
        overall_summary.setdefault(scenario_name, {})[
            'Cor2&Fragility: HV Score'
            ] = 'Supported' if c2_pf_supported else 'Check FAILs'
        results_log.append(f'\n--- Corollary 3: Empirical Falsifiability ---')
        results_log.append(
            f"   Mathematical Statement: Model is falsifiable if 'wiggles' (perturbations) degrade the HV score."
            )
        if c2_pf_supported:
            results_log.append(
                f'   Supported: Perturbation Fragility holds, suggesting the model is exposed to empirical tests.'
                )
            overall_summary.setdefault(scenario_name, {})[
                'Cor3: Falsifiability'] = 'Supported (via Fragility)'
        else:
            results_log.append(
                f'   Partially Supported/Not Supported: Perturbation Fragility did not fully hold.'
                )
            overall_summary.setdefault(scenario_name, {})[
                'Cor3: Falsifiability'] = 'Check FAILs (via Fragility)'
        c4_supported = validate_superset_penalty(data_df, target_name,
            S_after_pruning, hv_S_optimal, all_var_names, results_log)
        overall_summary.setdefault(scenario_name, {})['Cor4: SupersetPenalty'
            ] = 'Supported' if c4_supported else 'Check FAILs'
        c5_supported = validate_bootstrap_robustness(data_df, target_name,
            S_after_pruning, hv_S_optimal, all_var_names, results_log,
            n_boot=n_bootstrap_samples)
        overall_summary.setdefault(scenario_name, {})[
            'Cor5: BootstrapRobustness'
            ] = 'Supported' if c5_supported else 'Check FAILs'
        print('\n'.join(results_log))
        set_global_df_for_caching(None)
    print("\n\n{'='*20} OVERALL SUMMARY OF PROPOSITION VALIDATION {'='*20}")
    for scenario, results in overall_summary.items():
        print(f'\n{scenario}:')
        for prop, status in sorted(results.items()):
            print(f'  {prop}: {status}')
    print(
        """
Note: 'Supported' indicates numerical results align with the proposition's claims under the scenario's assumptions and chosen parameters (e.g., tau, DL method, n_boot). 'Check WARNs/FAILs' means some discrepancies were found."""
        )
