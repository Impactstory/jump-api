# coding: utf-8

from cached_property import cached_property
from collections import defaultdict
import weakref
from kids.cache import cache
from collections import OrderedDict
import numpy as np
import scipy
from scipy.optimize import curve_fit

from app import use_groups
from app import use_groups_free_instant
from app import use_groups_lookup
from app import get_db_cursor
from app import DEMO_PACKAGE_ID
from util import format_currency
from util import format_percent
from util import format_with_commas

def display_usage(value):
    if value:
        return value
    else:
        return "—"

class Journal(object):
    years = range(0, 5)

    def __init__(self, issn_l, scenario=None, scenario_data=None, package_id=None):
        self.set_scenario(scenario)
        self.set_scenario_data(scenario_data)
        self.issn_l = issn_l
        self.package_id = package_id
        self.subscribed = False
        self.use_default_download_curve = False

    def set_scenario(self, scenario):
        if scenario:
            self.scenario = weakref.proxy(scenario)
            self.settings = self.scenario.settings
        else:
            self.scenario = None
            self.settings = None

    def set_scenario_data(self, scenario_data):
        self._scenario_data = scenario_data

    @cached_property
    def my_scenario_data_row(self):
        return self._scenario_data["unpaywall_downloads_dict"][self.issn_l] or {}

    @cached_property
    def title(self):
        return self.my_scenario_data_row.get("title", "")

    @cached_property
    def subject(self):
        return self.my_scenario_data_row.get("subject", "")

    @cached_property
    def publisher(self):
        return self.my_scenario_data_row.get("publisher", "")

    @cached_property
    def cost_subscription_2018(self):
        # return float(self.my_scenario_data_row.get("usa_usd", 0)) * (1 + self.settings.cost_content_fee_percent/float(100))
        my_lookup = self._scenario_data["prices"]
        if not my_lookup.get(self.issn_l):
            return None
        return float(my_lookup.get(self.issn_l)) * (1 + self.settings.cost_content_fee_percent/float(100))

    @cached_property
    def papers_2018(self):
        return self.my_scenario_data_row.get("num_papers_2018", 0)

    @cached_property
    def num_citations_historical_by_year(self):
        try:
            my_dict = self._scenario_data[self.package_id]["citation_dict"].get(self.issn_l, {})
        except KeyError:
            print "key error in num_citations_historical_by_year for {}".format(self.issn_l)
            return [0 for year in self.years]
        # the year is a string key alas
        if my_dict and isinstance(my_dict.keys()[0], int):
            return [my_dict.get(year, 0) for year in self.historical_years_by_year]
        else:
            return [my_dict.get(str(year), 0) for year in self.historical_years_by_year]

    @cached_property
    def num_citations(self):
        return round(np.mean(self.num_citations_historical_by_year), 4)

    @cached_property
    def num_authorships_historical_by_year(self):
        try:
            my_dict = self._scenario_data[self.package_id]["authorship_dict"].get(self.issn_l, {})
        except KeyError:
            print "key error in num_authorships_historical_by_year for {}".format(self.issn_l)
            return [0 for year in self.years]

        # the year is a string key alas
        if my_dict and isinstance(my_dict.keys()[0], int):
            return [my_dict.get(year, 0) for year in self.historical_years_by_year]
        else:
            return [my_dict.get(str(year), 0) for year in self.historical_years_by_year]

    @cached_property
    def num_authorships(self):
        return round(np.mean(self.num_authorships_historical_by_year), 4)

    @cached_property
    def oa_embargo_months(self):
        return self._scenario_data["embargo_dict"].get(self.issn_l, None)

    def set_subscribe(self):
        self.subscribed = True
        # invalidate cache
        for key in self.__dict__:
            if "actual" in key:
                del self.__dict__[key]

    def set_unsubscribe(self):
        self.subscribed = False
        # invalidate cache
        for key in self.__dict__:
            if "actual" in key:
                del self.__dict__[key]

    @cached_property
    def years_by_year(self):
        return [2019 + year_index for year_index in self.years]

    @cached_property
    def historical_years_by_year(self):
        # used for citation, authorship lookup
        return range(2015, 2019+1)

    @cached_property
    def cost_actual_by_year(self):
        if self.subscribed:
            return self.cost_subscription_by_year
        return self.cost_ill_by_year

    @cached_property
    def cost_actual(self):
        if self.subscribed:
            return self.cost_subscription
        return self.cost_ill


    @cached_property
    def cost_subscription_by_year(self):
        response = [round(((1+self.settings.cost_alacart_increase/float(100))**year) * self.cost_subscription_2018 )
                                            for year in self.years]
        return response

    @cached_property
    def cost_subscription(self):
        return round(np.mean(self.cost_subscription_by_year), 4)


    @cached_property
    def ncppu(self):
        if not self.use_paywalled or self.use_paywalled < 1:
            return None
        return round(self.cost_subscription_minus_ill/self.use_paywalled, 6)

    @cached_property
    def old_school_cpu(self):
        if not self.downloads_total or self.downloads_total < 1:
            return None
        return round(float(self.cost_subscription)/self.downloads_total, 6)

    @cached_property
    def use_weight_multiplier(self):
        if not self.downloads_total:
            return 1.0
        return float(self.use_total) / self.downloads_total


    @cached_property
    def use_free_instant_by_year(self):
        response = [0 for year in self.years]
        for group in use_groups_free_instant:
            for year in self.years:
                response[year] += self.__getattribute__("use_{}_by_year".format(group))[year]
        return response

    @cached_property
    def use_instant_by_year(self):
        response = [0 for year in self.years]
        for group in use_groups_free_instant + ["subscription"]:
            for year in self.years:
                response[year] += self.use_actual_by_year[group][year]
        return response

    @cached_property
    def use_instant(self):
        return round(np.mean(self.use_instant_by_year), 4)

    @cached_property
    def use_free_instant(self):
        # return round(np.mean(self.use_free_instant_by_year), 4)
        response = 0
        for group in use_groups_free_instant:
            response += self.__getattribute__("use_{}".format(group))
        return response

    @cached_property
    def downloads_subscription_by_year(self):
        return self.downloads_paywalled_by_year

    @cached_property
    def downloads_subscription(self):
        return self.downloads_paywalled

    @cached_property
    def use_subscription(self):
        return self.use_paywalled

    @cached_property
    def use_subscription_by_year(self):
        return [self.use_paywalled_by_year[year] for year in self.years]

    @cached_property
    def downloads_social_network_multiplier(self):
        if self.settings.include_social_networks:
            return self._scenario_data["social_networks"].get(self.issn_l, 0)
        else:
            return 0.0

    @cached_property
    def downloads_social_networks_by_year(self):
        response = [self.downloads_total_by_year[year] * self.downloads_social_network_multiplier for year in self.years]
        response = [min(response[year], self.downloads_total_by_year[year] - self.downloads_oa_by_year[year]) for year in self.years]
        response = [max(response[year], 0) for year in self.years]
        return response

    @cached_property
    def downloads_social_networks(self):
        return round(np.mean(self.downloads_social_networks_by_year), 4)

    @cached_property
    def use_social_networks_by_year(self):
        response = [self.use_total_by_year[year] * self.downloads_social_network_multiplier for year in self.years]
        response = [min(response[year], self.use_total_by_year[year] - self.use_oa_by_year[year]) for year in self.years]
        response = [max(response[year], 0) for year in self.years]
        return response

    @cached_property
    def use_social_networks(self):
        # return round(self.downloads_social_networks * self.use_weight_multiplier, 4)
        response = min(np.mean(self.use_social_networks_by_year), self.use_total - self.use_oa)
        return response


    @cached_property
    def downloads_ill_by_year(self):
        response = [self.settings.ill_request_percent_of_delayed/float(100) * self.downloads_paywalled_by_year[year] for year in self.years]
        response = [num if num else 0 for num in response]
        return response


    @cached_property
    def downloads_ill(self):
        return round(np.mean(self.downloads_ill_by_year), 4)

    @cached_property
    def use_ill(self):
        return self.settings.ill_request_percent_of_delayed/float(100) * self.use_paywalled

    @cached_property
    def use_ill_by_year(self):
        return [self.settings.ill_request_percent_of_delayed/float(100) * self.use_paywalled_by_year[year] for year in self.years]

    @cached_property
    def downloads_other_delayed_by_year(self):
        return [self.downloads_paywalled_by_year[year] - self.downloads_ill_by_year[year] for year in self.years]

    @cached_property
    def downloads_other_delayed(self):
        return round(np.mean(self.downloads_other_delayed_by_year), 4)

    @cached_property
    def use_other_delayed(self):
        return self.use_paywalled - self.use_ill

    @cached_property
    def use_other_delayed_by_year(self):
        return [self.use_paywalled_by_year[year] - self.use_ill_by_year[year] for year in self.years]

    @cached_property
    def downloads_backfile_by_year(self):
        if self.settings.include_backfile:
            scaled = [0 for year in self.years]
            for year in self.years:
                age = year
                new = 0.5 * ((self.downloads_by_age[age] * self.growth_scaling_downloads[year]) - (self.downloads_oa_by_age[year][age] * self.growth_scaling_oa_downloads[year]))
                scaled[year] = max(new, 0)
                for age in range(year+1, 5):
                    by_age = (self.downloads_by_age[age] * self.growth_scaling_downloads[year]) - (self.downloads_oa_by_age[year][age] * self.growth_scaling_oa_downloads[year])
                    by_age += max(new, 0)
                scaled[year] += by_age
                if scaled[year]:
                    scaled[year] += self.downloads_total_older_than_five_years
                scaled[year] *= (1 - self.downloads_social_network_multiplier)
            scaled = [max(0, num) for num in scaled]
            return scaled
        else:
            return [0 for year in self.years]


    @cached_property
    def downloads_backfile(self):
        return round(np.mean(self.downloads_backfile_by_year), 4)

    @cached_property
    def use_backfile_by_year(self):
        response = [max(0, round(self.downloads_backfile_by_year[year] * self.use_weight_multiplier, 4)) for year in self.years]
        response = [min(response[year], self.use_total_by_year[year] - self.use_oa_by_year[year]) for year in self.years]
        return response

    @cached_property
    def use_backfile(self):
        # response = [min(response[year], self.use_total_by_year[year] - self.use_oa_by_year[year]) for year in self.years]
        response = min(np.mean(self.downloads_backfile_by_year), self.use_total - self.use_oa - self.use_social_networks)
        return round(response, 4)

    @cached_property
    def num_oa_historical_by_year(self):
        # print "num_oa_historical_by_year", self.num_papers, [self.num_green_historical_by_year[year]+self.num_bronze_historical_by_year[year]+self.num_hybrid_historical_by_year[year] for year in self.years]
        # print "parts", self.num_papers
        # print "green", self.num_green_historical_by_year
        # print "bronze", self.num_bronze_historical_by_year
        # print "hybrid", self.num_hybrid_historical_by_year

        return [self.num_green_historical_by_year[year]+self.num_bronze_historical_by_year[year]+self.num_hybrid_historical_by_year[year] for year in self.years]

    @cached_property
    def downloads_oa_base(self):
        return round(np.sum([self.num_oa_for_convolving[age] * self.downloads_per_paper_by_age[age] for age in self.years]), 4)

    @cached_property
    def downloads_oa_by_year(self):
        # TODO add some growth by using num_oa_by_year instead of num_oa_by_year_historical
        response = [self.downloads_oa_base * self.growth_scaling_oa_downloads[year] for year in self.years]
        return response

    @cached_property
    def use_oa(self):
        # return round(self.downloads_oa * self.use_weight_multiplier, 4)
        # return self.use_oa_green + self.use_oa_bronze + self.use_oa_hybrid
        response = min(np.mean(self.use_oa_by_year), self.use_total)
        return round(response, 4)

    @cached_property
    def use_oa_by_year(self):
        # just making this stable prediction over next years
        # TODO fix
        response = [max(0, self.downloads_oa_by_year[year] * self.use_weight_multiplier) for year in self.years]
        response = [min(num, self.use_total_by_year[year]) for num in response]
        return response


    @cached_property
    def downloads_total_by_year(self):
        scaled = [self.downloads_scaled_by_counter_by_year[year] * self.growth_scaling_downloads[year] for year in self.years]
        return scaled

    @cached_property
    def downloads_total(self):
        return round(np.mean(self.downloads_total_by_year), 4)



    # used to calculate use_weight_multiplier so it can't use it
    @cached_property
    def use_total_by_year(self):
        return [self.downloads_total_by_year[year] + self.use_addition_from_weights*self.growth_scaling_downloads[year] for year in self.years]

    @cached_property
    def use_total(self):
        response = round(np.mean(self.use_total_by_year), 4)
        if response == 0:
            response = 0.0001
        return response


    @cached_property
    def raw_downloads_by_age(self):
        # isn't replaced by default if too low or not monotonically decreasing
        total_downloads_by_age_before_counter_correction = [self.my_scenario_data_row.get("downloads_{}y".format(age), 0) for age in self.years]
        total_downloads_by_age_before_counter_correction = [val if val else 0 for val in total_downloads_by_age_before_counter_correction]
        downloads_by_age = [num * self.downloads_counter_multiplier for num in total_downloads_by_age_before_counter_correction]
        return downloads_by_age


    @cached_property
    def curve_fit_for_downloads(self):
        x = np.array(self.years)
        y = np.array(self.downloads_by_age_before_counter_correction)
        initial_guess = (float(np.max(y)), 30.0, -1.0)  # determined empirically

        def func(x, a, b, c):
            try:
                response = b + a * np.exp(x/c)
            except:
                response = None
            return response

        try:
            pars, pcov = curve_fit(func, x, y, initial_guess)
        except:
            return {}

        y_fit = [func(a, pars[0], pars[1], pars[2]) for a in x]

        residuals = y - y_fit
        ss_res = np.sum(residuals**2) + 0.0001
        ss_tot = np.sum((y - np.mean(y))**2) + 0.0001
        r_squared = 1 - (ss_res / ss_tot)

        return {"y_fit": y_fit,
                "r_squared": r_squared,
                "params": pars}


    @cached_property
    def downloads_by_age_before_counter_correction(self):
        downloads_by_age_before_counter_correction = [self.my_scenario_data_row.get("downloads_{}y".format(age), 0) for age in self.years]
        downloads_by_age_before_counter_correction = [val if val else 0 for val in downloads_by_age_before_counter_correction]
        return downloads_by_age_before_counter_correction

    @cached_property
    def downloads_by_age(self):
        use_default_curve = False

        my_curve_fit = self.curve_fit_for_downloads
        if my_curve_fit and my_curve_fit["r_squared"] >= 0.75:
            # print u"GREAT curve fit for {}, r_squared {}".format(self.issn_l, my_curve_fit.get("r_squared", "no r_squared"))
            downloads_by_age_before_counter_correction_curve_to_use = my_curve_fit["y_fit"]
        else:
            # print u"bad curve fit for {}, r_squared {}".format(self.issn_l, my_curve_fit.get("r_squared", "no r_squared"))
            self.use_default_download_curve = True
            # from future of OA paper, modified to be just elsevier, all colours
            default_download_by_age = [0.371269, 0.137739, 0.095896, 0.072885, 0.058849]
            sum_total_downloads_by_age_before_counter_correction = np.sum(self.downloads_by_age_before_counter_correction)
            downloads_by_age_before_counter_correction_curve_to_use = [num*sum_total_downloads_by_age_before_counter_correction for num in default_download_by_age]

        downloads_by_age = [num * self.downloads_counter_multiplier for num in downloads_by_age_before_counter_correction_curve_to_use]
        return downloads_by_age


    @cached_property
    def downloads_total_older_than_five_years(self):
        return self.downloads_total - np.sum(self.downloads_by_age)

    @cached_property
    def downloads_per_paper_by_age(self):
        # TODO do separately for each type of OA
        # print [[float(num), self.num_papers, self.num_oa_historical] for num in self.downloads_by_age]

        if self.num_papers:
            return [float(num)/self.num_papers for num in self.downloads_by_age]
        return [0 for num in self.downloads_by_age]

    @cached_property
    def downloads_scaled_by_counter_by_year(self):
        # TODO is flat right now
        downloads_total_before_counter_correction_by_year = [max(1.0, self.my_scenario_data_row.get("downloads_total", 0.0)) for year in self.years]
        downloads_total_before_counter_correction_by_year = [val if val else 0.0 for val in downloads_total_before_counter_correction_by_year]
        downloads_total_scaled_by_counter = [num * self.downloads_counter_multiplier for num in downloads_total_before_counter_correction_by_year]
        return downloads_total_scaled_by_counter

    @cached_property
    def downloads_per_paper(self):
        per_paper = float(self.downloads_scaled_by_counter_by_year)/self.num_papers
        return per_paper



    @cached_property
    def num_oa_for_convolving(self):
        oa_in_order = self.num_oa_historical_by_year
        # oa_in_order.reverse()
        # print "\nself.num_oa_historical_by_year", self.num_papers, oa_in_order
        return [min(self.num_papers, self.num_oa_historical_by_year[year]) for year in self.years]

    @cached_property
    def downloads_oa_by_age(self):
        # TODO do separately for each type of OA and each year
        response = {}
        for year in self.years:
            response[year] = [(float(self.downloads_per_paper_by_age[age])*self.num_oa_for_convolving[age]) for age in self.years]
            if self.oa_embargo_months:
                for age in self.years:
                    if age*12 >= self.oa_embargo_months:
                        response[year][age] = self.downloads_by_age[age]
        return response

    @cached_property
    def downloads_paywalled_by_year(self):
        scaled = [self.downloads_total_by_year[year]
              - (self.downloads_backfile_by_year[year] + self.downloads_oa_by_year[year] + self.downloads_social_networks_by_year[year])
          for year in self.years]
        scaled = [max(0, num) for num in scaled]
        return scaled

    @cached_property
    def downloads_paywalled(self):
        return round(np.mean(self.downloads_paywalled_by_year), 4)

    @cached_property
    def use_paywalled(self):
        return max(0, self.use_total - self.use_free_instant)

    @cached_property
    def use_paywalled_by_year(self):
        return [max(0, self.use_total_by_year[year] - self.use_free_instant_by_year[year]) for year in self.years]

    @cached_property
    def downloads_counter_multiplier_normalized(self):
        return round(self.downloads_counter_multiplier / self.scenario.downloads_counter_multiplier, 4)

    @cached_property
    def use_weight_multiplier_normalized(self):
        return round(self.use_weight_multiplier / self.scenario.use_weight_multiplier, 4)

    @cached_property
    def downloads_actual(self):
        response = defaultdict(int)
        for group in use_groups:
            response[group] = round(np.mean(self.downloads_actual_by_year[group]), 4)
        return response

    @cached_property
    def use_actual(self):
        response = defaultdict(int)
        for group in use_groups:
            response[group] = self.__getattribute__("use_{}".format(group))
            if self.subscribed:
                response["ill"] = 0
                response["other_delayed"] = 0
            else:
                response["subscription"] = 0
        return response

    @cached_property
    def downloads_actual_by_year(self):
        #initialize
        my_dict = {}
        # include the if to skip this if no useage
        if self.downloads_total:
            for group in use_groups:
                my_dict[group] = self.__getattribute__("downloads_{}_by_year".format(group))
                if self.subscribed:
                    my_dict["ill"] = [0 for year in self.years]
                    my_dict["other_delayed"] = [0 for year in self.years]
                else:
                    my_dict["subscription"] = [0 for year in self.years]
        return my_dict

    @cached_property
    def use_actual_by_year(self):
        my_dict = {}
        for group in use_groups:
            # defaults
            my_dict[group] = self.__getattribute__("use_{}_by_year".format(group))
            if self.subscribed:
                my_dict["ill"] = [0 for year in self.years]
                my_dict["other_delayed"] = [0 for year in self.years]
            else:
                my_dict["subscription"] = [0 for year in self.years]
        return my_dict

    @cached_property
    def downloads_total_before_counter_correction(self):
        return max(1.0, self.my_scenario_data_row.get("downloads_total", 0.0))

    @cached_property
    def use_addition_from_weights(self):
        # using the average on purpose... by year too rough
        weights_addition = 0
        # the if is to help speed it up
        if self.num_citations or self.num_authorships:
            weights_addition = float(self.settings.weight_citation) * self.num_citations
            weights_addition += float(self.settings.weight_authorship) * self.num_authorships
            weights_addition = round(weights_addition, 4)
        return weights_addition

    @cached_property
    def downloads_counter_multiplier(self):
        try:
            counter_for_this_journal = self._scenario_data[self.package_id]["counter_dict"][self.issn_l]
            counter_multiplier = float(counter_for_this_journal) / self.downloads_total_before_counter_correction
        except:
            counter_multiplier = float(0)
        return counter_multiplier


    @cached_property
    def cost_ill(self):
        return round(np.mean(self.cost_ill_by_year), 4)

    @cached_property
    def cost_ill_by_year(self):
        return [round(self.downloads_ill_by_year[year] * self.settings.cost_ill, 4) for year in self.years]

    @cached_property
    def cost_subscription_minus_ill_by_year(self):
        return [self.cost_subscription_by_year[year] - self.cost_ill_by_year[year] for year in self.years]

    @cached_property
    def cost_subscription_minus_ill(self):
        return round(self.cost_subscription - self.cost_ill, 4)

    @cached_property
    def ncppu_rank(self):
        if self.ncppu:
            return self.scenario.ncppu_rank_lookup[self.issn_l]
        return None

    @cached_property
    def old_school_cpu_rank(self):
        if self.old_school_cpu:
            return self.scenario.old_school_cpu_rank_lookup[self.issn_l]
        return None

    @cached_property
    def cost_subscription_fuzzed(self):
        return self.scenario.cost_subscription_fuzzed_lookup[self.issn_l]

    @cached_property
    def cost_subscription_minus_ill_fuzzed(self):
        return self.scenario.cost_subscription_minus_ill_fuzzed_lookup[self.issn_l]

    @cached_property
    def ncppu_fuzzed(self):
        return self.scenario.ncppu_fuzzed_lookup[self.issn_l]

    @cached_property
    def use_total_fuzzed(self):
        return self.scenario.use_total_fuzzed_lookup[self.issn_l]

    @cached_property
    def downloads_fuzzed(self):
        return self.scenario.downloads_fuzzed_lookup[self.issn_l]

    @cached_property
    def num_authorships_fuzzed(self):
        return self.scenario.num_authorships_fuzzed_lookup[self.issn_l]

    @cached_property
    def num_citations_fuzzed(self):
        return self.scenario.num_citations_fuzzed_lookup[self.issn_l]

    @cached_property
    def curve_fit_for_num_papers(self):
        x = np.array(self.years)
        y = np.array(self.raw_num_papers_historical_by_year)

        initial_guess = (float(np.mean(y)), 0.05)  # determined empirically

        def func(x, b, m):
               return b + m * x

        try:
            pars, pcov = curve_fit(func, x, y, initial_guess)
        except:
            return {}

        y_fit = [func(a, pars[0], pars[1]) for a in x]

        residuals = y - y_fit
        ss_res = np.sum(residuals**2) + 0.0001
        ss_tot = np.sum((y - np.mean(y))**2) + 0.0001
        r_squared = 1 - (ss_res / ss_tot)

        y_extrap = [func(a, pars[0], pars[1]) for a in range(5, 10)]

        response = {"y_fit": y_fit,
                "r_squared": r_squared,
                "params": pars,
                "y_extrap": y_extrap
                }
        return response

    @cached_property
    def growth_scaling_downloads(self):
        return self.num_papers_growth_from_2018_by_year

    @cached_property
    def growth_scaling_oa_downloads(self):
        # todo add OA growing faster
        return self.growth_scaling_downloads

    @cached_property
    def num_papers_growth_from_2018_by_year(self):
        curve_fit = self.curve_fit_for_num_papers
        if curve_fit and curve_fit["y_fit"][4]:
            num_papers_2018 = curve_fit["y_fit"][4]
            return [round(float(x)/num_papers_2018, 4) for x in self.num_papers_by_year]
        return [0 for x in self.num_papers_by_year]

    @cached_property
    def num_papers_by_year(self):
        my_curve_fit = self.curve_fit_for_num_papers
        if not my_curve_fit:
            return [self.papers_2018 for year in self.years]
        return [max(0, num) for num in my_curve_fit["y_extrap"]]

    @cached_property
    def raw_num_papers_historical_by_year(self):
        if self.issn_l in self._scenario_data["num_papers"]:
            my_raw_numbers = self._scenario_data["num_papers"][self.issn_l]
            # historical goes up to 2019 but we don't have all the data for that yet

            # yeah this is ugly depends on whether cached or not yuck
            if isinstance(my_raw_numbers.keys()[0], int):
                response = [my_raw_numbers.get(year-1, 0) for year in self.historical_years_by_year]
            else:
                response = [my_raw_numbers.get(str(year-1), 0) for year in self.historical_years_by_year]
        else:
            response = [self.papers_2018 for year in self.years]

        return response

    @cached_property
    def num_papers(self):
        return round(np.mean(self.num_papers_by_year))

    @cached_property
    def use_instant_percent(self):
        if not self.use_total:
            return 0
        return min(100.0, round(100 * float(self.use_instant) / self.use_total, 4))

    @cached_property
    def use_free_instant_percent(self):
        if not self.use_total:
            return 0
        return min(100.0, round(100 * float(self.use_free_instant) / self.use_total, 4))

    @cached_property
    def use_instant_percent_by_year(self):
        if not self.downloads_total:
            return 0
        return [round(100 * float(self.use_instant_by_year[year]) / self.use_total_by_year[year], 4) if self.use_total_by_year[year] else None for year in self.years]


    @cached_property
    def num_oa_papers_multiplier(self):
        oa_adjustment_dict = self._scenario_data["oa_adjustment"].get(self.issn_l, None)
        if not oa_adjustment_dict:
            return 1.0
        if not oa_adjustment_dict["unpaywall_measured_fraction_3_years_oa"]:
            return 1.0
        response = float(oa_adjustment_dict["mturk_max_oa_rate"]) / (oa_adjustment_dict["unpaywall_measured_fraction_3_years_oa"])
        # print "num_oa_papers_multiplier", response, float(oa_adjustment_dict["mturk_max_oa_rate"]), (oa_adjustment_dict["unpaywall_measured_fraction_3_years_oa"])
        return response

    def get_oa_data(self, only_peer_reviewed=False):
        if only_peer_reviewed:
            submitted = "no_submitted"
        else:
            if self.settings.include_submitted_version:
                submitted = "with_submitted"
            else:
                submitted = "no_submitted"

        if self.settings.include_bronze:
            bronze = "with_bronze"
        else:
            bronze = "no_bronze"

        my_dict = defaultdict(dict)

        key = u"{}_{}".format(submitted, bronze)
        my_rows = self._scenario_data["oa"][key].get(self.issn_l, [])
        my_recent_rows = self._scenario_data["oa_recent"][key].get(self.issn_l, [])

        for row in my_rows:
            my_dict[row["fresh_oa_status"]][round(row["year_int"])] = round(row["count"])
            # my_dict[row["fresh_oa_status"]][round(row["year_int"])] = round(row["count"]) * self.num_oa_papers_multiplier

        for row in my_recent_rows:
            my_dict[row["fresh_oa_status"]][2019] = round(row["count"])
            # my_dict[row["fresh_oa_status"]][round(row["year_int"])] = round(row["count"]) * self.num_oa_papers_multiplier

        # print my_dict
        return my_dict


    @cached_property
    def num_green_historical_by_year(self):
        my_dict = self.get_oa_data()["green"]
        return [my_dict.get(year, 0) for year in self.historical_years_by_year]

    @cached_property
    def num_green_historical(self):
        return round(np.mean(self.num_green_historical_by_year), 4)

    @cached_property
    def downloads_oa_green(self):
        return round(np.sum([self.num_green_historical * self.downloads_per_paper_by_age[age] for age in self.years]), 4)

    @cached_property
    def use_oa_green(self):
        return round(self.downloads_oa_green * self.use_weight_multiplier, 4)


    @cached_property
    def num_hybrid_historical_by_year(self):
        my_dict = self.get_oa_data()["hybrid"]
        return [my_dict.get(year, 0) for year in self.historical_years_by_year]

    @cached_property
    def num_hybrid_historical(self):
        return round(np.mean(self.num_hybrid_historical_by_year), 4)

    @cached_property
    def downloads_oa_hybrid(self):
        return round(np.sum([self.num_hybrid_historical * self.downloads_per_paper_by_age[age] for age in self.years]), 4)

    @cached_property
    def use_oa_hybrid(self):
        return round(self.downloads_oa_hybrid * self.use_weight_multiplier, 4)


    @cached_property
    def num_bronze_historical_by_year(self):
        my_dict = self.get_oa_data()["bronze"]
        response = [my_dict.get(year, 0) for year in self.historical_years_by_year]
        if self.oa_embargo_months:
            for age in self.years:
                if age*12 < self.oa_embargo_months:
                    response[age] = 0
        return response

    @cached_property
    def num_bronze_historical(self):
        return round(np.mean(self.num_bronze_historical_by_year), 4)

    @cached_property
    def downloads_oa_bronze(self):
        return round(np.sum([self.num_bronze_historical * self.downloads_per_paper_by_age[age] for age in self.years]), 4)


    @cached_property
    def use_oa_bronze(self):
        return round(self.downloads_oa_bronze * self.use_weight_multiplier, 4)


    @cached_property
    def num_peer_reviewed_historical_by_year(self):
        my_dict = self.get_oa_data(only_peer_reviewed=True)
        response = defaultdict(int)
        for oa_type in my_dict:
            for year in self.historical_years_by_year:
                response[year] += my_dict[oa_type].get(year, 0)
        return [response[year] for year in self.historical_years_by_year]

    @cached_property
    def num_peer_reviewed_historical(self):
        return round(np.mean(self.num_peer_reviewed_historical_by_year), 4)

    @cached_property
    def downloads_oa_peer_reviewed(self):
        return round(np.sum([self.num_peer_reviewed_historical * self.downloads_per_paper_by_age[age] for age in self.years]), 4)

    @cached_property
    def use_oa_peer_reviewed(self):
        return round(self.downloads_oa_peer_reviewed * self.use_weight_multiplier, 4)

    @cached_property
    def is_society_journal(self):
        is_society_journal = self._scenario_data["society"].get(self.issn_l, "YES")
        return is_society_journal == "YES"

    def to_dict_report(self):
        response = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed,
                    "usage_total_fuzzed": self.use_total_fuzzed,
                    "num_authorships_fuzzed": self.num_authorships_fuzzed,
                    "num_citations_fuzzed": self.num_citations_fuzzed,
                    "num_papers": self.num_papers,
                    "use_instant_percent": self.use_instant_percent,
                    "use_instant_percent_by_year": self.use_instant_percent_by_year,
                    "oa_embargo_months": self.oa_embargo_months,
        }
        return response

    def to_dict_impact(self):
        response = OrderedDict()
        response["meta"] = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed}
        table_row = OrderedDict()
        table_row["total_usage"] = round(self.use_total)
        table_row["downloads"] = round(self.downloads_total)
        table_row["citations"] = round(self.num_citations, 1)
        table_row["authorships"] = round(self.num_authorships, 1)
        response["table_row"] = table_row
        return response

    def to_dict_overview(self):
        response = OrderedDict()
        response["meta"] = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed}
        table_row = OrderedDict()
        table_row["ncppu"] = display_usage(self.ncppu)
        table_row["cost"] = self.cost_actual
        table_row["use"] = self.use_total
        table_row["instant_usage_percent"] = round(self.use_instant_percent, 1)
        response["table_row"] = table_row

        for k, v in self.to_dict_slider().iteritems():
                response[k] = v

        return response

    def to_dict_export(self):
        response = self.to_dict_table()
        response["table_row"]["ncppu_fuzzed"] = self.ncppu_fuzzed
        response["table_row"]["subscription_cost_fuzzed"] = self.cost_subscription_fuzzed
        response["table_row"]["subscription_minus_ill_cost_fuzzed"] = self.cost_subscription_minus_ill_fuzzed
        response["table_row"]["usage_fuzzed"] = self.use_total_fuzzed
        response["table_row"]["downloads_fuzzed"] = self.downloads_fuzzed
        response["table_row"]["citations_fuzzed"] = self.num_citations_fuzzed
        response["table_row"]["authorships_fuzzed"] = self.num_authorships_fuzzed
        return response

    def to_dict_table(self):
        response = OrderedDict()
        response["meta"] = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed}
        table_row = OrderedDict()

        # table
        table_row["ncppu"] = display_usage(self.ncppu)
        table_row["ncppu_rank"] = display_usage(self.ncppu_rank)
        table_row["cost"] = self.cost_actual
        table_row["usage"] = round(self.use_total)
        table_row["instant_usage_percent"] = round(self.use_instant_percent)
        table_row["free_instant_usage_percent"] = round(self.use_free_instant_percent)

        # cost
        table_row["subscription_cost"] = round(self.cost_subscription)
        table_row["ill_cost"] = round(self.cost_ill)
        table_row["subscription_minus_ill_cost"] = round(self.cost_subscription_minus_ill)
        # table_row["old_school_cpu"] = display_usage(self.old_school_cpu)
        # table_row["old_school_cpu_rank"] = display_usage(self.old_school_cpu_rank)

        # fulfillment
        table_row["use_asns_percent"] = round(float(100)*self.use_actual["social_networks"]/self.use_total)
        table_row["use_oa_percent"] = round(float(100)*self.use_actual["oa"]/self.use_total)
        table_row["use_backfile_percent"] = round(float(100)*self.use_actual["backfile"]/self.use_total)
        table_row["use_subscription_percent"] = round(float(100)*self.use_actual["subscription"]/self.use_total)
        table_row["use_ill_percent"] = round(float(100)*self.use_actual["ill"]/self.use_total)
        table_row["use_other_delayed_percent"] =  round(float(100)*self.use_actual["other_delayed"]/self.use_total)

        # oa
        table_row["use_green_percent"] = round(float(100)*self.use_oa_green/self.use_total)
        table_row["use_hybrid_percent"] = round(float(100)*self.use_oa_hybrid/self.use_total)
        table_row["use_bronze_percent"] = round(float(100)*self.use_oa_bronze/self.use_total)
        table_row["use_peer_reviewed_percent"] =  round(float(100)*self.use_oa_peer_reviewed/self.use_total)

        # impact
        table_row["downloads"] = round(self.downloads_total)
        table_row["citations"] = round(self.num_citations, 1)
        table_row["authorships"] = round(self.num_authorships, 1)

        response["table_row"] = table_row

        return response


    def to_dict_cost(self):
        response = OrderedDict()
        response["meta"] = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed}
        table_row = OrderedDict()
        table_row["ncppu"] = display_usage(self.ncppu)
        table_row["scenario_cost"] = round(self.cost_actual)
        table_row["subscription_cost"] = round(self.cost_subscription)
        table_row["ill_cost"] = round(self.cost_ill)
        table_row["real_cost"] = round(self.cost_subscription_minus_ill)
        response["table_row"] = table_row
        return response


    def to_dict_timeline(self):
        response = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed,
                    "year": self.years_by_year,
                    "year_historical": self.historical_years_by_year,
                    "oa_embargo_months": self.oa_embargo_months,
                    "cost_actual_by_year": self.cost_actual_by_year,
                    "use_total_by_year": self.use_total_by_year
        }
        for k, v in vars(self).iteritems():
            if k.endswith("by_year") and not k.endswith("years_by_year") and ("weighted_by_year" not in k):
                response[k] = v
        # make sure we don't miss these because they haven't been initialized
        for group in use_groups:
            field = "use_{}_by_year".format(group)
            response[field] = self.__getattribute__(field)
        return response

    def to_dict_details(self):
        response = OrderedDict()

        response["top"] = {
                "issn_l": self.issn_l,
                "title": self.title,
                "subject": self.subject,
                "publisher": self.publisher,
                "is_society_journal": self.is_society_journal,
                "subscribed": self.subscribed,
                "num_papers": self.num_papers,
                "cost_subscription": format_currency(self.cost_subscription),
                "cost_ill": format_currency(self.cost_ill),
                "cost_actual": format_currency(self.cost_actual),
                "cost_subscription_minus_ill": format_currency(self.cost_subscription_minus_ill),
                "ncppu": format_currency(self.ncppu, True),
                "use_instant_percent": self.use_instant_percent,
                "api_journal_raw_default_settings": "https://unpaywall-jump-api.herokuapp.com/journal/issn_l/{}?email=YOUR_EMAIL_ADDRESS".format(self.issn_l)
        }

        group_list = []
        for group in use_groups:
            group_dict = OrderedDict()
            group_dict["group"] = use_groups_lookup[group]["display"]
            group_dict["usage"] = format_with_commas(round(self.use_actual[group]))
            group_dict["usage_percent"] = format_percent(round(float(100)*self.use_actual[group]/self.use_total))
            # group_dict["timeline"] = u",".join(["{:>7}".format(self.use_actual_by_year[group][year]) for year in self.years])
            for year in self.years:
                group_dict["year_"+str(2020 + year)] = format_with_commas(round(self.use_actual_by_year[group][year]))
            group_list += [group_dict]
        response["fulfillment"] = {
            "headers": [
                {"text": "Type", "value": "group"},
                {"text": "Usage (projected annual)", "value": "usage"},
                {"text": "Usage (percent)", "value": "usage_percent"},
                {"text": "Usage projected 2020", "value": "year_2020"},
                {"text": "2021", "value": "year_2021"},
                {"text": "2022", "value": "year_2022"},
                {"text": "2023", "value": "year_2023"},
                {"text": "2024", "value": "year_2024"},
            ],
            "data": group_list
            }
        response["fulfillment"]["use_actual_by_year"] = self.use_actual_by_year
        response["fulfillment"]["downloads_per_paper_by_age"] = self.downloads_per_paper_by_age

        oa_list = []
        for oa_type in ["green", "hybrid", "bronze"]:
            oa_dict = OrderedDict()
            use = self.__getattribute__("use_oa_{}".format(oa_type))
            oa_dict["oa_status"] = oa_type.title()
            # oa_dict["num_papers"] = round(self.__getattribute__("num_{}_historical".format(oa_type)))
            oa_dict["usage"] = format_with_commas(use)
            oa_dict["usage_percent"] = format_percent(round(float(100)*use/self.use_total))
            oa_list += [oa_dict]
        oa_list += [OrderedDict([("oa_status", "*Total*"),
                                # ("num_papers", round(self.num_oa_historical)),
                                ("usage", format_with_commas(self.use_oa)),
                                ("usage_percent", format_percent(round(100*float(self.use_oa)/self.use_total)))])]
        response["oa"] = {
            "oa_embargo_months": self.oa_embargo_months,
            "headers": [
                {"text": "OA Type", "value": "oa_status"},
                # {"text": "Number of papers (annual)", "value": "num_papers"},
                {"text": "Usage (projected annual)", "value": "usage"},
                {"text": "Percent of all usage", "value": "usage_percent"},
            ],
            "data": oa_list
            }

        impact_list = [
            OrderedDict([("impact", "Downloads"),
                         ("raw", format_with_commas(self.downloads_total)),
                         ("weight", 1),
                         ("contribution", format_with_commas(self.downloads_total))]),
            OrderedDict([("impact", "Citations to papers in this journal"),
                         ("raw", format_with_commas(self.num_citations, 1)),
                         ("weight", self.settings.weight_citation),
                         ("contribution", format_with_commas(self.num_citations * self.settings.weight_citation))]),
            OrderedDict([("impact", "Authored papers in this journal"),
                         ("raw", format_with_commas(self.num_authorships, 1)),
                         ("weight", self.settings.weight_authorship),
                         ("contribution", format_with_commas(self.num_authorships * self.settings.weight_authorship))]),
            OrderedDict([("impact", "*Total*"),
                         ("raw", "-"),
                         ("weight", "-"),
                         ("contribution", format_with_commas(self.use_total))])
            ]
        response["impact"] = {
            "usage_total": self.use_total,
            "headers": [
                {"text": "Impact", "value": "impact"},
                {"text": "Raw (projected annual)", "value": "raw"},
                {"text": "Weight", "value": "weight"},
                {"text": "Usage contribution", "value": "contribution"},
            ],
            "data": impact_list
            }

        cost_list = []
        for cost_type in ["cost_actual_by_year", "cost_subscription_by_year", "cost_ill_by_year", "cost_subscription_minus_ill_by_year"]:
            cost_dict = OrderedDict()
            if cost_type == "cost_actual_by_year":
                cost_dict["cost_type"] = "*Your scenario cost*"
            else:
                cost_dict["cost_type"] = cost_type.replace("cost_", "").replace("_", " ").title()
                cost_dict["cost_type"] = cost_dict["cost_type"].replace("Ill", "ILL")
            costs = self.__getattribute__(cost_type)
            for year in self.years:
                cost_dict["year_"+str(2020 + year)] = format_currency(costs[year])
            cost_list += [cost_dict]
            cost_dict["cost_avg"] = format_currency(self.__getattribute__(cost_type.replace("_by_year", "")))
            if self.use_paywalled:
                cost_dict["cost_per_use"] = format_currency(self.__getattribute__(cost_type.replace("_by_year", "")) / float(self.use_paywalled), True)
            else:
                cost_dict["cost_per_use"] = "no paywalled usage"
        response["cost"] = {
            "subscribed": self.subscribed,
            "ncppu": format_currency(self.ncppu, True),
            "headers": [
                {"text": "Cost Type", "value": "cost_type"},
                {"text": "Cost (projected annual)", "value": "cost_avg"},
                {"text": "Non-net cost per paid use", "value": "cost_per_use"},
                {"text": "Cost projected 2020", "value": "year_2020"},
                {"text": "2021", "value": "year_2021"},
                {"text": "2022", "value": "year_2022"},
                {"text": "2023", "value": "year_2023"},
                {"text": "2024", "value": "year_2024"},
            ],
            "data": cost_list
            }

        from apc_journal import ApcJournal
        my_apc_journal = ApcJournal(self.issn_l, self._scenario_data)
        response["apc"] = {
            "apc_price": my_apc_journal.apc_price_display,
            "annual_projected_cost": my_apc_journal.cost_apc_historical,
            "annual_projected_fractional_authorship": my_apc_journal.fractional_authorships_total,
            "annual_projected_num_papers": my_apc_journal.num_apc_papers_historical,
        }

        response_debug = {}
        response_debug["scenario_settings"] = self.settings.to_dict()
        response_debug["use_instant_percent"] = self.use_instant_percent
        response_debug["use_instant_percent_by_year"] = self.use_instant_percent_by_year
        response_debug["oa_embargo_months"] = self.oa_embargo_months
        response_debug["num_papers"] = self.num_papers
        response_debug["use_weight_multiplier_normalized"] = self.use_weight_multiplier_normalized
        response_debug["use_weight_multiplier"] = self.use_weight_multiplier
        response_debug["downloads_counter_multiplier_normalized"] = self.downloads_counter_multiplier_normalized
        response_debug["downloads_counter_multiplier"] = self.downloads_counter_multiplier
        response_debug["use_instant_by_year"] = self.use_instant_by_year
        response_debug["use_instant_percent_by_year"] = self.use_instant_percent_by_year
        response_debug["use_actual_by_year"] = self.use_actual_by_year
        response_debug["use_actual"] = self.use_actual
        response_debug["use_oa_green"] = self.use_oa_green
        response_debug["use_oa_hybrid"] = self.use_oa_hybrid
        response_debug["use_oa_bronze"] = self.use_oa_bronze
        response_debug["use_oa_peer_reviewed"] = self.use_oa_peer_reviewed
        response_debug["use_oa"] = self.use_oa
        response_debug["downloads_total_by_year"] = self.downloads_total_by_year
        response_debug["use_default_download_curve"] = self.use_default_download_curve
        response_debug["downloads_total_older_than_five_years"] = self.downloads_total_older_than_five_years
        response_debug["raw_downloads_by_age"] = self.raw_downloads_by_age
        response_debug["downloads_by_age"] = self.downloads_by_age
        response_debug["downloads_oa_by_age"] = self.downloads_oa_by_age
        response_debug["num_papers_by_year"] = self.num_papers_by_year
        response_debug["num_papers_growth_from_2018_by_year"] = self.num_papers_growth_from_2018_by_year
        response_debug["raw_num_papers_historical_by_year"] = self.raw_num_papers_historical_by_year
        response_debug["ncppu_rank"] = self.ncppu_rank
        response["debug"] = response_debug

        return response

    def to_dict_oa(self):
        response = OrderedDict()
        response["meta"] = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed}
        table_row = OrderedDict()
        table_row["use_oa_percent"] = round(float(100)*self.use_actual["oa"]/self.use_total)
        table_row["use_green_percent"] = round(float(100)*self.use_oa_green/self.use_total)
        table_row["use_hybrid_percent"] = round(float(100)*self.use_oa_hybrid/self.use_total)
        table_row["use_bronze_percent"] = round(float(100)*self.use_oa_bronze/self.use_total)
        table_row["use_peer_reviewed_percent"] =  round(float(100)*self.use_oa_peer_reviewed/self.use_total)
        response["table_row"] = table_row
        response["bin"] = int(float(100)*self.use_actual["oa"]/self.use_total)/10
        return response

    def to_dict_fulfillment(self):
        response = OrderedDict()
        response["meta"] = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject,
                    "subscribed": self.subscribed}
        table_row = OrderedDict()
        table_row["instant_usage_percent"] = round(self.use_instant_percent, 1)
        table_row["use_asns"] = round(float(100)*self.use_actual["social_networks"]/self.use_total)
        table_row["use_oa"] = round(float(100)*self.use_actual["oa"]/self.use_total)
        table_row["use_backfile"] = round(float(100)*self.use_actual["backfile"]/self.use_total)
        table_row["use_subscription"] = round(float(100)*self.use_actual["subscription"]/self.use_total)
        table_row["use_ill"] = round(float(100)*self.use_actual["ill"]/self.use_total)
        table_row["use_other_delayed"] =  round(float(100)*self.use_actual["other_delayed"]/self.use_total)
        response["table_row"] = table_row
        response["bin"] = int(self.use_instant_percent)/10
        for k, v in self.to_dict_slider().iteritems():
                response[k] = v

        return response


    def to_dict_slider(self):
        response = {"issn_l": self.issn_l,
                "title": self.title,
                "subject": self.subject,
                "use_total": self.use_total,
                "cost_subscription": self.cost_subscription,
                "cost_ill": self.cost_ill,
                "cost_subscription_minus_ill": self.cost_subscription_minus_ill,
                "ncppu": self.ncppu,
                "subscribed": self.subscribed,
                "use_instant": self.use_instant,
                "use_instant_percent": self.use_instant_percent,
                }
        response["use_groups_free_instant"] = {}
        for group in use_groups_free_instant:
            response["use_groups_free_instant"][group] = self.__getattribute__("use_{}".format(group))
        response["use_groups_if_subscribed"] = {"subscription": self.use_subscription}
        response["use_groups_if_not_subscribed"] = {"ill": self.use_ill, "other_delayed": self.use_other_delayed}
        return response

    def to_dict_raw(self):
        response = OrderedDict()
        response["meta"] = {"issn_l": self.issn_l,
                    "title": self.title,
                    "subject": self.subject}
        table_row = OrderedDict()

        # cost
        table_row["subscription_cost"] = round(self.cost_subscription)
        table_row["ill_cost"] = round(self.cost_ill)

        # fulfillment
        table_row["use_asns"] = self.use_social_networks
        table_row["use_oa"] = self.use_oa
        table_row["use_backfile"] = self.use_backfile
        table_row["use_subscription"] = self.use_subscription
        table_row["use_ill"] = self.use_ill
        table_row["use_other_delayed"] =  self.use_other_delayed

        # oa
        table_row["use_green"] = self.use_oa_green
        table_row["use_hybrid"] = self.use_oa_hybrid
        table_row["use_bronze"] = self.use_oa_bronze
        table_row["use_peer_reviewed"] =  self.use_oa_peer_reviewed

        # impact
        table_row["total_usage"] = round(self.use_total, 2)
        table_row["downloads"] = round(self.downloads_total, 2)
        table_row["citations"] = round(self.num_citations, 2)
        table_row["authorships"] = round(self.num_authorships, 2)

        response["table_row"] = table_row

        return response


    def to_dict(self):
        return {"issn_l": self.issn_l,
                "title": self.title,
                "subject": self.subject,
                "num_authorships": self.num_authorships,
                "num_citations": self.num_citations,
                "use_paywalled": self.use_paywalled,
                "use_instant": self.use_instant,
                "usage": self.use_total,
                "cost_subscription": self.cost_subscription,
                "cost_ill": self.cost_ill,
                "cost_subscription_minus_ill": self.cost_subscription_minus_ill,
                "ncppu": self.ncppu,
                "subscribed": self.subscribed
                }

    def __repr__(self):
        return u"<{} ({}) {}>".format(self.__class__.__name__, self.issn_l, self.title)



# observation_year 	total views 	total views percent of 2018 	total oa views 	total oa views percent of 2018
# 2018 	25,565,054.38 	1.00 	12,664,693.62 	1.00
# 2019 	28,162,423.76 	1.10 	14,731,000.96 	1.16
# 2020 	30,944,070.68 	1.21 	17,033,520.59 	1.34
# 2021 	34,222,756.60 	1.34 	19,830,049.25 	1.57
# 2022 	38,000,898.80 	1.49 	23,092,284.75 	1.82
# 2023 	42,304,671.82 	1.65 	26,895,794.03 	2.12



