import logging

import numpy
import pandas

from hts.hierarchy import HierarchyTree
from hts._t import Model
from hts.model import TimeSeriesModel
from hts.utils import suppress_stdout_stderr

logger = logging.getLogger(__name__)
logging.getLogger('fbprophet').setLevel(logging.ERROR)


try:
    from fbprophet import Prophet
except ImportError:  # pragma: no cover
    logger.error('Mapping requires folium==0.10.0 to be installed, geo mapping will not work')


class FBProphetModel(TimeSeriesModel):
    # TODO: include history to calculate residuals
    def __init__(self, node: HierarchyTree, **kwargs):
        super().__init__(Model.prophet.name, node, **kwargs)
        self.cap = None
        self.floor = None
        self.include_history = False

    def create_model(self,
                     capacity_max=None,
                     capacity_min=None,
                     **kwargs):
        self.cap = capacity_max
        self.floor = capacity_min

        if not capacity_max and not capacity_min:
            growth = 'linear'
        else:
            growth = 'logistic'
            if self.cap:
                self.node.item['cap'] = capacity_max
            if self.floor:
                self.node.item['floor'] = capacity_min

        model = Prophet(growth=growth, **kwargs)
        if self.node.exogenous:
            for ex in self.node.exogenous:
                model.add_regressor(ex)
        return model

    def _reformat(self, node):
        if isinstance(node, pandas.Series):
            node = pandas.DataFrame(node)
        df = node.item.rename(columns={self.node.key: 'y'})
        df['ds'] = df.index
        return df.reset_index(drop=True)

    def fit(self):
        df = self._reformat(self.node.item)
        with suppress_stdout_stderr():
            self.model = self.model.fit(df)
        return self

    def predict(self,
                node: HierarchyTree,
                freq='D', periods=1, include_history=True,
                **predict_args):

        df = self._reformat(node)
        future = self.model.make_future_dataframe(periods=periods,
                                                  freq=freq,
                                                  include_history=include_history)
        if self.cap:
            future['cap'] = self.cap
        if self.floor:
            future['floor'] = self.floor

        self.forecast = self.model.predict(future)
        merged = pandas.merge(df, self.forecast, on='ds')
        self.residual = (merged['yhat'] - merged['y']).values
        self.mse = numpy.mean(numpy.array(self.residual) ** 2)
        if self.cap is not None:
            self.forecast.yhat = numpy.exp(self.forecast.yhat)
        if self.transform:
            self.forecast.yhat = self.transformer.inverse_transform(self.forecast.yhat)
            self.forecast.trend = self.transformer.inverse_transform(self.forecast.trend)
            for component in ["seasonal", "daily", "weekly", "yearly", "holidays"]:
                if component in self.forecast.columns.tolist():
                    inv_transf = self.transformer.inverse_transform(getattr(self.forecast, component))
                    setattr(self.forecast, component, inv_transf)
        return self.model
